"""Allow ``python -m backend.app.ai.rag`` to rebuild the index without the
runpy double-import warning that ``python -m backend.app.ai.rag.index`` emits.
"""

from .index import main

raise SystemExit(main())
