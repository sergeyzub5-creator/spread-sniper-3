from difflib import SequenceMatcher

from PySide6.QtCore import QTimer


class SpreadPairSuggestionsMixin:
    def _popular_for_exchange(self, exchange_name):
        if not exchange_name:
            return []
        popular = self._pair_popular_cache.get(exchange_name)
        if popular is None:
            pairs = self._pair_cache.get(exchange_name) or []
            popular = self._build_popular_list(pairs)
            self._pair_popular_cache[exchange_name] = popular
        return list(popular)

    def _build_popular_list(self, pairs):
        normalized_pairs = self._normalize_pairs(pairs)
        if not normalized_pairs:
            return list(self.POPULAR_PAIRS)

        pair_set = set(normalized_pairs)
        popular = []
        for pair in self.POPULAR_PAIRS:
            if pair in pair_set:
                popular.append(pair)

        for pair in normalized_pairs:
            if pair not in popular:
                popular.append(pair)
            if len(popular) >= self.POPULAR_SUGGESTIONS:
                break

        return popular[: self.POPULAR_SUGGESTIONS]

    def _schedule_pair_suggestions(self, index, query):
        timers = getattr(self, "_pair_suggest_timers", None)
        if timers is None:
            timers = {}
            self._pair_suggest_timers = timers

        queries = getattr(self, "_pair_suggest_queries", None)
        if queries is None:
            queries = {}
            self._pair_suggest_queries = queries

        normalized_query = self._normalize_pair(query)
        queries[index] = normalized_query

        timer = timers.get(index)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda idx=index: self._apply_scheduled_pair_suggestions(idx))
            timers[index] = timer

        # Small debounce keeps typing responsive on large pair lists.
        timer.start(55)

    def _apply_scheduled_pair_suggestions(self, index):
        queries = getattr(self, "_pair_suggest_queries", None) or {}
        query = self._normalize_pair(queries.get(index, ""))

        suggestions = self._build_suggestions(index, query)
        self._update_completer_items(index, suggestions)

        column = self._column(index)
        if (
            column is not None
            and suggestions
            and column.pair_completer is not None
            and column.pair_edit is not None
            and column.pair_edit.hasFocus()
        ):
            column.pair_completer.complete()

    def _build_suggestions(self, index, query):
        pairs = self._pairs_for_index(index)
        if not pairs:
            return []

        q = self._normalize_pair(query)
        if not q:
            exchange_name = self._get_selected_exchange(index)
            return self._popular_for_exchange(exchange_name)

        exact = None
        starts = []
        contains = []
        for pair in pairs:
            if pair == q:
                exact = pair
                continue

            if pair.startswith(q):
                starts.append(pair)
                continue

            pos = pair.find(q)
            if pos >= 0:
                contains.append((pos, len(pair), pair))

        starts.sort(key=lambda item: (len(item), item))
        contains.sort(key=lambda item: (item[0], item[1], item[2]))

        result = []
        if exact:
            result.append(exact)
        result.extend(starts)
        result.extend(pair for _pos, _length, pair in contains)
        if len(result) >= self.MAX_SUGGESTIONS or len(q) <= 1:
            return result[: self.MAX_SUGGESTIONS]

        # Fuzzy fallback is bounded to keep UI smooth on very large lists.
        seed = set(result)
        fuzzy = []
        scanned = 0
        first_char = q[0]
        for pair in pairs:
            if pair in seed:
                continue
            if first_char not in pair:
                continue
            scanned += 1
            ratio = SequenceMatcher(None, q, pair).ratio()
            if ratio < 0.45:
                continue
            fuzzy.append((ratio, len(pair), pair))
            if scanned >= 320:
                break

        fuzzy.sort(key=lambda item: (-item[0], item[1], item[2]))
        result.extend(pair for _ratio, _length, pair in fuzzy)
        return result[: self.MAX_SUGGESTIONS]

    def _update_completer_items(self, index, items):
        column = self._column(index)
        if column is None or column.pair_model is None:
            return
        column.pair_model.setStringList(self._normalize_pairs(items))

