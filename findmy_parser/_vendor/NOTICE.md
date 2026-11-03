# Vendored third-party code

## ccl_bplist.py

- Source: https://github.com/cclgroupltd/ccl-bplist (`ccl_bplist.py`, `master` branch)
- Author: Alex Caithness / CCL Forensics (CCL Solutions Group)
- Version: 0.21 (per the module's own `__version__`)
- License: BSD 3-Clause (full text retained in the file's header, unmodified)

Not published on PyPI - CCL distributes it as a single file meant to be
copied into a project, so it's vendored here rather than declared as a
normal pip dependency. This keeps findmy_parser dependency-free/installable
offline, which matters for the forensic-workstation use case this tool is
built for.

Used by `findmy_parser/fmipcore.py` to decode NSKeyedArchiver-wrapped
bplists (a common Apple serialisation format for cache files - `plistlib`
alone parses the raw structure but doesn't dereference the `$objects`
table or reassemble `NSDictionary`/`NSArray`/`NSDate` from their archived
form). The file is unmodified from upstream.
