"""Hidden-layer scan fixtures: picture-of-text pages carrying an invisible (render mode 3) text layer
placed at chosen offsets from the printed words, with a machine-readable expected file per document.

Entry points (run from the repository root):

    .venv/bin/python -I hidden_layer/build.py --out <dir>
    .venv/bin/python -I hidden_layer/verify_docs.py <dir>

See ``hidden_layer/README.md``.
"""
