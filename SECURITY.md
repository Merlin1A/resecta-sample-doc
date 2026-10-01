# Security Policy

resecta-sample-doc generates synthetic test documents for the Resecta iOS
redaction app — a multi-exhibit loan/mortgage packet, a sample bank statement
and a set of capture masters — and test fixtures, most of them derived from the
packet. The statement and the packet are bundled in the app; everything else is
test input. It processes no real user data. The security-relevant property of
this repository is that its outputs stay synthetic and deterministic.

## Reporting a vulnerability

- **Email:** `security@resecta.app`.
- **GitHub Security Advisories:** open a private advisory on this repository's
  *Security* tab.

Please do not open public issues for security reports until coordinated
disclosure has been agreed upon.

### What to expect

- **Acknowledgement:** within 7 days of receipt.
- **Triage update:** within 30 days of acknowledgement.

## Scope

**In scope:**

- The Python generator code (`packet/`, `generate_statement.py`,
  `statement_data.py`, `verify.py`, and related modules).
- Any defect that could cause real personal data to enter a generated document,
  or that breaks the byte-reproducibility of the outputs.

**Out of scope:**

- The Resecta iOS app and the data pipeline — report those through their own
  repositories.
- The bundled Inter font (SIL OFL 1.1) — report upstream at
  [rsms/inter](https://github.com/rsms/inter).

The fixture PDFs under `planted/` and `robustness/` are unusual or malformed on
purpose: byte-damaged, encrypted, at a page-size or page-count limit, or
carrying an embedded file or a JavaScript action that only assigns a string.
They exist to test how a PDF importer and the verification tooling handle such
input; that is not a defect.

## Synthetic-data posture

The persons and organizations the generated documents are about are invented;
real agencies, courts and statutes appear only as the furniture of the public
forms and filings the exhibits imitate.
Identifiers are invented or taken from published test and reserved ranges:
555-01xx telephone numbers, the 4111… test card number, the Social Security
Administration's advertising range, and the long-voided 078-05-1120 as a value
the app must reject. The SSNs and ITINs that must read as valid are invented
numbers. City names and ZIP codes are real, for plausibility.
E-mail addresses use the RFC 2606 reserved example domains, and no production
or real-world document is included.

Nothing in this policy is legal advice.
