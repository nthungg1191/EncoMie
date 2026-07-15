"""
Qt Worker thread for running render jobs without blocking the UI.
Supports concurrent rendering of multiple video pairs.
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker, QWaitCondition
from core.video_processor import FilePair, RenderConfig, render_pair, build_pairs


class SingleRenderJob(QThread):
    # Signals specific to this individual job
    progress = pyqtSignal(str, float, str)  # index, percent, message
    log_line = pyqtSignal(str)              # raw ffmpeg log line
    done = pyqtSignal(str, str)             # index, output_path
    error = pyqtSignal(str, str)            # index, error_message

    def __init__(self, pair: FilePair, config: RenderConfig, batch_index: int, total: int, pause_checker, parent=None):
        super().__init__(parent)
        self.pair = pair
        self.config = config
        self.batch_index = batch_index
        self.total = total
        self.pause_checker = pause_checker
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        def _progress(pct, msg, _batch=self.batch_index, _total=self.total, _pair_idx=self.pair.index):
            if self.pause_checker:
                self.pause_checker()
            if self._abort:
                raise InterruptedError("Render đã bị dừng")
            # Replace [pair.index] with [batch/total] for correct progress display
            msg_with_batch = msg.replace(f"[{_pair_idx}]", f"[{_batch}/{_total}]")
            self.progress.emit(_pair_idx, pct, msg_with_batch)

        def _log(line):
            self.log_line.emit(line)

        try:
            out = render_pair(self.pair, self.config, _progress, _log, should_abort=lambda: self._abort)
            self.done.emit(self.pair.index, out)
        except InterruptedError:
            self.error.emit(self.pair.index, "Đã dừng")
        except Exception as e:
            self.error.emit(self.pair.index, str(e))


class RenderWorker(QThread):
    # Public Signals (matched with MainWindow slots)
    progress = pyqtSignal(float, str)       # unified percent, message
    log_line = pyqtSignal(str)              # raw ffmpeg log line
    pair_done = pyqtSignal(str, str)        # index, output_path
    pair_error = pyqtSignal(str, str)       # index, error_message
    all_done = pyqtSignal(int, int)         # success_count, error_count
    stopped = pyqtSignal()
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(self, pairs: list[FilePair], config: RenderConfig, parent=None):
        super().__init__(parent)
        self.pairs = pairs
        self.config = config
        self._abort = False
        self._paused = False
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()
        
        # State tracking
        self._active_jobs = {}         # pair.index -> SingleRenderJob
        self._pending_pairs = list(pairs)
        self._total = len(pairs)
        self._success = 0
        self._errors = 0
        self._job_progress = {}        # pair.index -> float (percent)
        self._job_messages = {}        # pair.index -> str (last status msg)
        self._completed_pairs = set()

    def abort(self):
        self._abort = True
        self.resume()
        for job in list(self._active_jobs.values()):
            job.abort()
        self.quit()

    def pause(self):
        with QMutexLocker(self._pause_mutex):
            self._paused = True
        self.paused.emit()

    def resume(self):
        should_emit = False
        with QMutexLocker(self._pause_mutex):
            if self._paused:
                self._paused = False
                self._pause_condition.wakeAll()
                should_emit = True
        if should_emit:
            self.resumed.emit()

    def _wait_if_paused(self):
        locker = QMutexLocker(self._pause_mutex)
        while self._paused and not self._abort:
            self._pause_condition.wait(self._pause_mutex)

    def run(self):
        self._success = 0
        self._errors = 0
        self._active_jobs.clear()
        self._pending_pairs = list(self.pairs)
        self._job_progress.clear()
        self._job_messages.clear()
        self._completed_pairs.clear()

        # If empty queue, exit immediately
        if not self.pairs:
            self.all_done.emit(0, 0)
            return

        # Start initial concurrent batch
        self._start_next_jobs()

        # Start local event loop to handle signals from SingleRenderJobs
        self.exec()

        # Event loop exited
        if self._abort:
            self.stopped.emit()
        else:
            self.all_done.emit(self._success, self._errors)

    def _start_next_jobs(self):
        if self._abort:
            return

        max_concurrent = getattr(self.config, "max_concurrent_renders", 2)
        while len(self._active_jobs) < max_concurrent and self._pending_pairs:
            pair = self._pending_pairs.pop(0)
            
            # Batch index is sequence number starting from 1
            batch_index = self._total - len(self._pending_pairs)
            
            job = SingleRenderJob(pair, self.config, batch_index, self._total, self._wait_if_paused)
            job.progress.connect(self._on_job_progress)
            job.log_line.connect(self._on_job_log)
            job.done.connect(self._on_job_done)
            job.error.connect(self._on_job_error)
            
            self._active_jobs[pair.index] = job
            job.start()

        # If no active jobs and no pending queue, stop event loop
        if not self._active_jobs and not self._pending_pairs:
            self.quit()

    def _on_job_progress(self, idx: str, pct: float, msg: str):
        self._job_progress[idx] = pct
        self._job_messages[idx] = msg
        self._emit_unified_progress()

    def _on_job_log(self, line: str):
        self.log_line.emit(line)

    def _on_job_done(self, idx: str, out_path: str):
        self._completed_pairs.add(idx)
        self._job_progress[idx] = 100.0
        self._success += 1
        
        # Clean up job reference
        if idx in self._active_jobs:
            self._active_jobs[idx].wait()
            del self._active_jobs[idx]

        self.pair_done.emit(idx, out_path)
        self._emit_unified_progress()
        self._start_next_jobs()

    def _on_job_error(self, idx: str, err_msg: str):
        self._completed_pairs.add(idx)
        self._job_progress[idx] = 100.0  # Count as done progress-wise
        
        # If it was aborted, we don't count it as a standard error
        if err_msg != "Đã dừng":
            self._errors += 1
            self.pair_error.emit(idx, err_msg)

        # Clean up job reference
        if idx in self._active_jobs:
            self._active_jobs[idx].wait()
            del self._active_jobs[idx]

        self._emit_unified_progress()
        self._start_next_jobs()

    def _emit_unified_progress(self):
        # Calculate unified progress based on completed jobs and progress of active jobs
        total_pct_sum = 0.0
        for pair in self.pairs:
            if pair.index in self._completed_pairs:
                total_pct_sum += 100.0
            else:
                total_pct_sum += self._job_progress.get(pair.index, 0.0)

        unified_pct = total_pct_sum / self._total
        
        # Formulate a helpful status message
        active_msgs = []
        for idx, job in self._active_jobs.items():
            pct_val = self._job_progress.get(idx, 0.0)
            active_msgs.append(f"#{idx} ({pct_val:.0f}%)")
            
        status_msg = f"Đang render: {', '.join(active_msgs)} | Tổng: {unified_pct:.1f}%"
        self.progress.emit(unified_pct, status_msg)


class PairingWorker(QThread):
    """Quick worker to scan folders and build pairs (can be slow on network drives)."""
    done = pyqtSignal(list)      # list[FilePair]
    error = pyqtSignal(str)

    def __init__(self, audio_folder: str, srt_folder: str, parent=None):
        super().__init__(parent)
        self.audio_folder = audio_folder
        self.srt_folder = srt_folder

    def run(self):
        try:
            pairs = build_pairs(self.audio_folder, self.srt_folder)
            self.done.emit(pairs)
        except Exception as e:
            self.error.emit(str(e))
