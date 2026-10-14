"""Migration et reconstitution de l'historique millésimé (2014-2025).

Isolée conformément à l'ADR 0008 pour découpler les corrections d'archives manuelles
du runtime de production de la base de données.
"""

from pathlib import Path
from typing import Any

import yaml


def compute_historical_attributions_map(
    res_dir: Path | str,
) -> tuple[set[int], dict[str, list[tuple[str, int, int]]]]:
    """Reconstitue la cartographie exacte des attributions historiques millésimées (2014-2025).

    Retourne:
        - editions: L'ensemble des millésimes concernés (2014..2025).
        - user_attributions: Dictionnaire associant chaque donneur_id à la liste de ses
          attributions sous la forme (beneficiaire_id, year, order_index).
    """
    root = Path(res_dir)

    def _load_yaml(p: Path) -> Any:
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    d25_in = _load_yaml(root / "2025" / "data_in.yml")
    d25_out = _load_yaml(root / "2025" / "data_out.yml")
    d24_in = _load_yaml(root / "2024" / "data_in.yml")
    d24_out = _load_yaml(root / "2024" / "data_out.yml")
    d23_in = _load_yaml(root / "2023" / "2023_data_in.yml")
    d23_out = _load_yaml(root / "2023" / "2023_data_out.yml")
    d22_in = _load_yaml(root / "2022" / "data_in_2022.yml")
    d22_out = _load_yaml(root / "2022" / "data_out_2022.yml")
    d21_in = _load_yaml(root / "__bk" / "data_2021.yml")
    d21_out = _load_yaml(root / "__bk" / "data_export_2021.yml")
    data_19_raw = _load_yaml(root / "__bk" / "data.yml") or []
    d19_out = {item["id"]: item.get("history", []) for item in data_19_raw}
    data_18_raw = _load_yaml(root / "__bk" / "data_2018.yml") or []
    d18_in = {item["id"]: item.get("history", []) for item in data_18_raw}

    known_pairs: dict[tuple[str, str], int] = {}
    for u, d in d25_out.items():
        if len(d.get("history", [])) > len(d25_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2025
    for u, d in d24_out.items():
        if len(d.get("history", [])) > len(d24_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2024
    for u, d in d23_out.items():
        if len(d.get("history", [])) > len(d23_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2023
    for u, d in d22_out.items():
        if len(d.get("history", [])) > len(d22_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2022
    for u, d in d21_out.items():
        if len(d.get("history", [])) > len(d21_in.get(u, {}).get("history", [])):
            known_pairs[(u, d["history"][-1])] = 2021
    for u, h in d19_out.items():
        h_prev = d18_in.get(u, [])
        if len(h) > len(h_prev):
            known_pairs[(u, h[-1])] = 2019

    editions: set[int] = set()
    user_attributions: dict[str, list[tuple[str, int, int]]] = {}

    for u, udata in sorted(d25_out.items()):
        h = udata.get("history", [])
        user_entries: list[tuple[str, int, int]] = []
        user_years: list[int | None] = [None] * len(h)

        for idx, b in enumerate(h):
            if (u, b) in known_pairs:
                user_years[idx] = known_pairs[(u, b)]
            elif u == "jdenis" and b == "scarrea" and ("jdenis", "scarre") in known_pairs:
                user_years[idx] = known_pairs[("jdenis", "scarre")]

        for idx in range(len(h)):
            if user_years[idx] is None:
                if u == "cmouret" and idx == 3 and h[idx] == "aboinet":
                    user_years[idx] = 2018
                elif u in ("fleduff", "schouteau") and idx < 4:
                    user_years[idx] = 2015 + idx
                elif u == "tmoro" and idx == 0:
                    user_years[idx] = 2018
                elif u == "jdenis" and idx == 1:
                    user_years[idx] = 2015
                else:
                    init_len = len(d18_in.get(u, []))
                    user_years[idx] = 2017 - (init_len - 1 - idx)

        for idx, b in enumerate(h):
            norm_b = "scarre" if b == "scarrea" else b
            yr = user_years[idx]
            if yr is None:
                raise ValueError(f"Year is None for {u} -> {b} at index {idx}")
            editions.add(yr)
            user_entries.append((norm_b, yr, idx))

        user_attributions[u] = user_entries

    return editions, user_attributions
