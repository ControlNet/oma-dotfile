# OMO Gitignore Policy

This repository tracks durable OMO project knowledge and planning artifacts while ignoring runtime session state.

Track these paths:
- `.omo/knowledges/` for reusable knowledge notes
- `.omo/notepads/` for project notepad records
- `.omo/plans/` for saved work plans

Ignore these paths:
- `.omo/boulder.json` runtime continuation state
- `.omo/run-continuation/` session continuation cache

Do not ignore the whole `.omo/` directory because Git cannot re-include nested untracked files reliably when the parent directory itself is ignored.
