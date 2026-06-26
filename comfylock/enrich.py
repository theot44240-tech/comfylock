"""Enrich model records with canonical, durable references.

A raw download URL rots: a repo gets renamed, a CDN link expires. A *canonical*
reference (a HuggingFace ``repo``/``file``/``revision``, or a Civitai
``model_id``/``version_id``) survives, and lets ``unpack`` reconstruct a working
download URL when the original one 404s ("dead URL recovery").

These parsers are deterministic and offline: they read what is already encoded in
a model's URL/mirrors. Enrichment is therefore opt-in (``pack --enrich hf`` /
``--enrich civitai``) but free of network calls and new dependencies -- ``pack``
stays zero-network for users who want pure offline operation.

A model whose URL carries no recognisable HF/Civitai reference is left untouched.
"""

from __future__ import annotations

import urllib.parse

from .model import Model

SOURCES = ("hf", "civitai")


def parse_hf_url(url: str) -> tuple[str, str] | None:
    """Return ``(repo_id, filename)`` from a HuggingFace URL, or None.

    Handles ``hf://org/repo/path/to/file`` and the HTTPS ``resolve`` form
    ``https://huggingface.co/org/repo/resolve/<rev>/path/to/file``.
    """
    low = url.lower()
    if low.startswith("hf://"):
        parts = url[len("hf://"):].split("/")
        if len(parts) < 3:
            return None
        return f"{parts[0]}/{parts[1]}", "/".join(parts[2:])
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host not in ("huggingface.co", "hf.co") and not host.endswith(".huggingface.co"):
        return None
    segs = [s for s in parsed.path.split("/") if s]
    # org / repo / resolve|blob / <rev> / file...
    if len(segs) >= 5 and segs[2] in ("resolve", "blob"):
        repo_id = f"{segs[0]}/{segs[1]}"
        filename = "/".join(segs[4:])
        return repo_id, filename
    return None


def parse_civitai_url(url: str) -> tuple[int | None, int | None] | None:
    """Return ``(model_id, version_id)`` from a Civitai URL, or None.

    Recognises the API download form ``/api/download/models/<versionId>`` and the
    web form ``/models/<modelId>?modelVersionId=<versionId>``. Either id may be
    None when only one is encoded in the URL.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host != "civitai.com" and not host.endswith(".civitai.com"):
        return None
    segs = [s for s in parsed.path.split("/") if s]
    query = dict(urllib.parse.parse_qsl(parsed.query))
    model_id: int | None = None
    version_id: int | None = None

    def _int(value: str | None) -> int | None:
        if value and value.isdigit():
            return int(value)
        return None

    if len(segs) >= 4 and segs[0] == "api" and segs[1] == "download" and segs[2] == "models":
        version_id = _int(segs[3])
    elif len(segs) >= 2 and segs[0] == "models":
        model_id = _int(segs[1])
        version_id = _int(query.get("modelVersionId"))
    if model_id is None and version_id is None:
        return None
    return model_id, version_id


def enrich_model(model: Model, sources: list[str]) -> list[str]:
    """Populate canonical references on ``model`` in place. Returns notes added.

    Only fills a field that is still empty (never overwrites an explicit value),
    and only from URLs already present on the model.
    """
    notes: list[str] = []
    for url in model.urls():
        if "hf" in sources and not (model.hf_repo_id and model.hf_filename):
            hf = parse_hf_url(url)
            if hf is not None:
                model.hf_repo_id, model.hf_filename = hf
                notes.append(f"{model.name}: hf -> {hf[0]}/{hf[1]}")
        if "civitai" in sources and not (
            model.civitai_model_id or model.civitai_version_id
        ):
            cv = parse_civitai_url(url)
            if cv is not None:
                if cv[0] is not None:
                    model.civitai_model_id = cv[0]
                if cv[1] is not None:
                    model.civitai_version_id = cv[1]
                notes.append(f"{model.name}: civitai -> model={cv[0]} version={cv[1]}")
    return notes


def recovery_urls(model: Model) -> list[str]:
    """Reconstruct download URLs from a model's canonical references.

    When the primary ``url`` 404s, these let ``unpack`` recover the file from its
    durable HF/Civitai identity ("dead URL recovery"). HuggingFace resolves to the
    ``main`` revision (the lock does not pin an HF commit yet); Civitai uses the
    version id's API download endpoint.
    """
    out: list[str] = []
    if model.hf_repo_id and model.hf_filename:
        out.append(
            f"https://huggingface.co/{model.hf_repo_id}"
            f"/resolve/main/{model.hf_filename}"
        )
    if model.civitai_version_id:
        out.append(
            f"https://civitai.com/api/download/models/{model.civitai_version_id}"
        )
    return out


def download_candidates(model: Model) -> list[str]:
    """All download URLs to try in order: primary, mirrors, then recovery URLs."""
    seen: dict[str, None] = {}
    for url in model.urls() + recovery_urls(model):
        if url and url not in seen:
            seen[url] = None
    return list(seen)


def resolve_sources(raw: list[str] | None) -> list[str]:
    """Validate ``--enrich`` values; ``["all"]`` expands to every source."""
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        key = item.strip().lower()
        if key == "all":
            return list(SOURCES)
        if key in SOURCES and key not in out:
            out.append(key)
        elif key not in SOURCES:
            raise RuntimeError(
                f"Unknown enrich source {item!r}. Valid: {', '.join(SOURCES)}, all."
            )
    return out
