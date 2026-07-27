from __future__ import annotations

from . import ab_stage_v2_walkforward as runner
from .ab_stage_v2_data import prepare_dataset


def main() -> None:
    runner.prepare_dataset = prepare_dataset
    runner.main()


if __name__ == "__main__":
    main()
