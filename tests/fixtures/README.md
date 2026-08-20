Test fixtures for .record parsing

- `DFC948EE-XXXX-4D3A-9E44-10B162BF9898/` — a real (anonymised) sample
  `.record` fixture, wrapped in a Physical-Analyzer-style extra folder.
- `synthetic/` — a generated fixture tree covering nested PA export
  depths, duplicate/dedup cases, format sniffing (bplist/XML plist/JSON),
  numeric-epoch timestamps, an unknown tracker, a corrupted file, and
  fmipcore `Items.data`/`Devices.data`. Regenerate with
  `python tests/fixtures/generate_synthetic.py`.
