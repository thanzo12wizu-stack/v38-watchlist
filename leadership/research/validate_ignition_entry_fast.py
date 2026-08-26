from __future__ import annotations

import validate_ignition_entry as base

_original_event_peer_returns = base.rs.event_peer_returns
_peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}


def cached_event_peer_returns(stock_ret, members, pos, horizon):
    key = (tuple(members), int(pos), int(horizon))
    if key not in _peer_cache:
        _peer_cache[key] = _original_event_peer_returns(stock_ret, members, pos, horizon)
    return _peer_cache[key]


base.rs.event_peer_returns = cached_event_peer_returns


if __name__ == "__main__":
    base.main()
