import time

from core.utils.thread_pool import ThreadManager, Worker


class SpreadPairLoaderMixin:
    def _trace_pair_loader(self, event, **fields):
        trace = getattr(self, "_trace", None)
        if callable(trace):
            trace(f"pairs.{event}", **fields)

    def _get_pair_state(self, exchange_name):
        return str(self._pair_cache_state.get(exchange_name, "unknown") or "unknown")

    def _set_pair_state(self, exchange_name, state):
        self._pair_cache_state[exchange_name] = str(state or "unknown")

    def _can_retry_pairs(self, exchange_name, force=False):
        now = time.monotonic()
        if force:
            self._pair_last_retry_ts[exchange_name] = now
            return True

        cooldown = float(getattr(self, "_pair_retry_cooldown_sec", 2.5) or 2.5)
        last_ts = float(self._pair_last_retry_ts.get(exchange_name, 0.0) or 0.0)
        if now - last_ts < cooldown:
            return False

        self._pair_last_retry_ts[exchange_name] = now
        return True

    def _ensure_pairs_loaded(self, exchange_name, force=False):
        if not exchange_name:
            return
        if exchange_name in self._pair_loading:
            self._trace_pair_loader("load_skip", exchange=exchange_name, reason="already_loading")
            return

        has_cache = exchange_name in self._pair_cache
        cache_state = self._get_pair_state(exchange_name)

        if not force:
            if has_cache and cache_state in {"ok", "empty"}:
                self._trace_pair_loader("load_skip", exchange=exchange_name, reason=f"cache_{cache_state}")
                return
            if has_cache and cache_state in {"error", "transient_empty"} and not self._can_retry_pairs(exchange_name):
                self._trace_pair_loader("load_skip", exchange=exchange_name, reason="retry_cooldown")
                return
        else:
            self._can_retry_pairs(exchange_name, force=True)
        self._trace_pair_loader("load_start", exchange=exchange_name, force=bool(force), cache_state=cache_state)

        self._pair_loading.add(exchange_name)
        self._set_pair_state(exchange_name, "loading")
        self._refresh_pair_controls()

        worker = Worker(self._load_pairs_task, exchange_name)
        self._pair_workers[exchange_name] = worker
        worker.signals.result.connect(lambda pairs, name=exchange_name: self._on_pairs_loaded(name, pairs))
        worker.signals.error.connect(lambda _error, name=exchange_name: self._on_pairs_error(name))
        worker.signals.finished.connect(lambda name=exchange_name: self._on_pairs_finished(name))
        ThreadManager().start(worker)

    def _load_pairs_task(self, exchange_name):
        return self._runtime_service.load_pairs(exchange_name)

    def _on_pairs_loaded(self, exchange_name, payload):
        strict = False
        refreshable = False
        pairs = payload
        if isinstance(payload, dict):
            strict = bool(payload.get("strict", False))
            refreshable = bool(payload.get("refreshable", False))
            pairs = payload.get("pairs", [])

        normalized = self._normalize_pairs(pairs)
        if not normalized and not strict:
            normalized = list(self.POPULAR_PAIRS)

        self._pair_cache[exchange_name] = normalized
        if normalized:
            self._pair_popular_cache[exchange_name] = self._build_popular_list(normalized)
            self._set_pair_state(exchange_name, "ok")
        else:
            self._pair_popular_cache[exchange_name] = []
            self._set_pair_state(exchange_name, "transient_empty" if refreshable else "empty")
        self._trace_pair_loader(
            "load_done",
            exchange=exchange_name,
            strict=bool(strict),
            refreshable=bool(refreshable),
            count=len(normalized),
            state=self._get_pair_state(exchange_name),
        )

        for column in self._iter_columns():
            if column.selected_exchange != exchange_name:
                continue
            if column.selected_pair and column.selected_pair not in normalized:
                self._clear_selected_pair(column.index)

    def _on_pairs_error(self, exchange_name):
        if self._runtime_service.is_pairs_source_strict(exchange_name):
            self._pair_cache[exchange_name] = []
            self._pair_popular_cache[exchange_name] = []
        else:
            self._pair_cache[exchange_name] = list(self.POPULAR_PAIRS)
            self._pair_popular_cache[exchange_name] = self._build_popular_list(self.POPULAR_PAIRS)
        self._set_pair_state(exchange_name, "error")
        self._trace_pair_loader("load_error", exchange=exchange_name, state="error")

    def _on_pairs_finished(self, exchange_name):
        self._pair_loading.discard(exchange_name)
        self._pair_workers.pop(exchange_name, None)
        self._refresh_pair_controls()
        self._refresh_trade_controls_safe()
        self._trace_pair_loader("load_finished", exchange=exchange_name)

    def _pairs_for_index(self, index):
        exchange_name = self._get_selected_exchange(index)
        if not exchange_name:
            return []
        return list(self._pair_cache.get(exchange_name) or [])
