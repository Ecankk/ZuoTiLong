# Extra bank staging adapters

These scripts turn a local, fixed-revision source checkout into reviewable JSONL
records. They do not modify the application database, read or write personal
.mathlens data, import third-party material into the application, or copy
source assets. Adapter output can contain copyrighted question text, so keep it
in ignored local storage such as tmp or a private user data directory.

## Inputs

- S02 cxy-daguan reads library/bundled-library.json and resolves image
  references through the repository assetMap. Original source strings,
  aliases, applicability labels, upstream hashes, and image hashes stay
  separate. Mixed or multiple lineage claims are marked for review; the
  adapter never chooses one claim as the authoritative book/exam identity.
- S03 zhangyu-1000t reads only HTML chapters explicitly labeled 强化篇
  (chapter-32 through chapter-67 by default). It stores the displayed
  chapter-local number and exact HTML locator. It does not assert an official
  printed question number, a print-page number, or an A/B/C group. In
  particular, a page labeled “2026 张宇考研数学 1000 题刷题版” is not
  automatically identified as the distinct title
  《考研数学题源探析经典1000题》.

## Commands

S03:

    python scripts/export_extra_bank.py --source S03 --source-root <local-zhangyu-checkout> --revision 19f626daefe25fe0e0d76abc30413b697fe4ce24 --chapters 32-67 --output tmp/extra-bank/zhangyu-strong.jsonl

S02:

    python scripts/export_extra_bank.py --source S02 --source-root <local-cxy-checkout> --revision 7e79423253454dfb32246b6a84c7d6fd6efaa5b8 --ids 2314,1234 --output tmp/extra-bank/cxy-sample.jsonl

Use actual upstream question IDs for an S02 sample. The limit option is
available for format smoke checks. Outputs are staging records, not compatible
import packages for the current image-only import_image_bank function.

## Record boundaries

- Source UID, revision, source-file checksum and record/fragment checksum
  preserve where a record came from. They are file identity fields, not
  mathematical or semantic fingerprints.
- Identity preserves book/exam claims without assigning an unverified
  printing, original page, or exam identity. Claimed applicability categories
  are not used as exam identity.
- Content keeps stem, choices, answer, explanation and figure references in
  separate fields. A missing answer is left missing.
- Availability reports resource presence. Math review status stays
  not_reviewed; file completeness and a rendered formula do not establish
  mathematical correctness.
- No adapter links duplicate questions. Text comparison, shared answer hashes,
  source labels and category overlap are insufficient to decide whether two
  problems are equivalent.
