"""personas.py -- the Hartwell household + org entities, minted ONCE (single source).

Every value here is fictional and minted once, so a value lives in exactly one constant and cannot
drift across exhibits (the shared-value map). Occurrences (occurrences.py) reference these
constants; exhibit generators draw them.

Discipline: every character is printable ASCII. No minted name/lender/employer/bank/routing value ever
enters a shipped gazetteer -- this module is design data only. All values are fictional and
disclosed as such in the manifest.
"""
from __future__ import annotations

# ==================================================================================================
# 1. The Hartwell household (every value minted once, never reused across a real credit-report shape)
# ==================================================================================================

# -- Delia R. Hartwell -- primary borrower, US citizen, W-2 employee, taxpayer ----------------------
DELIA_NAME = "Delia Hartwell"            # clean two-token Title-Case (must-fire surface)
DELIA_NAME_MI = "Delia R. Hartwell"      # middle-initial surface (should-fire: NLTagger span break)
DELIA_NAME_CAPS = "DELIA HARTWELL"       # ALL-CAPS surface (should-fire: NLTagger miss)
DELIA_SSN = "502-19-7438"                # area 502 (001-899, !=666), valid -> fires with label
DELIA_SSN_MASKED = "XXX-XX-7438"         # masked-form should-fire (breaks the \d runs)
DELIA_DOB = "03/14/1985"                 # numeric, label-anchored
DELIA_DOB_TEXTUAL = "March 14, 1985"     # textual DOB (C4: month-name alternation fires)
DELIA_DL = "D4729153"                    # California DL, matches ^[A-Z][0-9]{7}$
DELIA_CC = "4111 1111 1111 1111"         # Visa test PAN (Luhn + IIN + 16d), never-issued
DELIA_CC_MASKED = "**** 1111"            # masked credit-card watch
DELIA_EMAIL = "d.hartwell@example.net"   # RFC-2606 reserved domain
DELIA_PHONE_HOME = "(208) 555-0147"
DELIA_PHONE_CELL = "916-555-0182"        # CA area retained post-relocation (format zoo)
DELIA_PHONE_WORK = "208.555.0119"        # dotted (format zoo)
DELIA_ACCT_CHK = "480026184402"          # 12-digit checking (dodges 10-digit phone + 13-digit cc)
DELIA_ACCT_401K = "700415592031"         # 12-digit 401k
DELIA_ACCT_MM = "529184007731"           # 12-digit money market
DELIA_ACCT_MASKED = "XXXXXX3265"         # primary checking masked (= STMT account masked; cross-doc)

# -- Mateo Hartwell -- additional borrower, resident alien, joint filer -----------------------------
MATEO_NAME = "Mateo Hartwell"            # clean two-token Title-Case (must-fire)
MATEO_NAME_CAPS = "MATEO HARTWELL"       # ALL-CAPS surface (should-fire)
MATEO_ITIN = "970-85-6042"               # area 9NN, group 85 in {70-88}, valid ITIN; SSN rejects 9NN
MATEO_DOB = "07/22/1986"
MATEO_PASSPORT = "N42851960"             # Mexico issuer, matches ^[A-Z][0-9]{8}$
MATEO_EMAIL = "m.hartwell@example.org"
MATEO_PHONE_WORK = "+1 208-555-0173"     # +1 prefix (format zoo)
MATEO_ACCT_SAV = "836470091254"          # 12-digit savings
MATEO_ACCT_MASKED = "XXXXXX1180"         # 401k masked

# -- Lena Hartwell -- dependent child (b. 2014) -----------------------------------------------------
LENA_NAME = "Lena Hartwell"
LENA_SSN = "521-44-8093"                 # area 521, valid
LENA_DOB = "09/03/2014"

# -- Theo Hartwell -- dependent child (b. 2017) -----------------------------------------------------
THEO_NAME = "Theo Hartwell"
THEO_SSN = "438-26-7159"                 # area 438, valid
THEO_DOB = "12/15/2017"

# -- Karen Delgado -- loan originator (a PERSON; fires as name) -------------------------------------
KAREN_NAME = "Karen Delgado"
KAREN_EMAIL = "k.delgado@example.com"

# ==================================================================================================
# 2. Addresses. Multi-line addresses are tuples of rendered lines (one span/line).
#    No directional-with-period ("N.") in any street name -- it breaks the address detector's
#    [a-zA-Z\s] street class.
# ==================================================================================================
ADDR_RESIDENCE = ("4127 Wrenfield Place", "Boise, ID 83702")            # shared household residence
ADDR_FORMER_CA = ("812 Aldergrove Avenue", "Modesto, CA 95354")        # Delia former (CA-DL reconcile)
ADDR_PO_DELIA = "P.O. Box 2215, Boise, ID 83701"                       # Delia mailing P.O. Box
ADDR_PO_MATEO = "P.O. Box 6841, Boise, ID 83707"                       # Mateo mailing P.O. Box
ADDR_EMPLOYER = "2900 Commerce Park Drive, Meridian, ID 83642"         # Tannersworth employer address

# ==================================================================================================
# 3. Organization entities. Org-style -> do NOT fire as personalName; never
#    gazetteered. Design data only.
# ==================================================================================================
LENDER_NAME = "Quillhaven Lending"                       # the lender (FDIC=0, USPTO knockout clear)
BANK_NAME = "Sablebrook Bank"                            # = the FROZEN statement's brand (reused)
EMPLOYER_NAME = "Tannersworth Freight Systems, Inc."     # non-financial employer

# ==================================================================================================
# 4. Numeric identifiers shared across exhibits
# ==================================================================================================
EIN_TANNERSWORTH = "36-4419872"          # valid campus prefix 36 + EIN label -> fires
RTN_BANK = "213004929"                   # must-fire RTN: prefix 21, mod-10 ok, group-00 SSN-invalid
RTN_WATCH = "311210000"                  # valid RTN, no routing kw -> stays 0.50 (watch)

# ==================================================================================================
# 5. Negative-program values (the per-exhibit N-* rows). Named so every negative
#    is traceable; each is engine-INVALID by construction (shape / checksum / range / keyword).
# ==================================================================================================
# credit-card negatives (URLA-B Sec 2 tradelines)
CC_LUHN_FAIL = "4111 1111 1111 1112"     # Luhn fails -> cc rejects (occ_urlab_21)
CC_BAD_IIN = "9111 1111 1111 1110"       # Luhn-pass but lead 9 -> no IIN family (N-CC-1)
CC_SHORT = "5412 3456 7890"              # 12 digits < 13 -> below cc shape (N-CC-2)

# routing negatives
RTN_CHECKSUM_FAIL = "618220000"          # prefix 61 ok, mod-10 fails (occ_ach_04)
RTN_BAD_PREFIX = "901230047"             # prefix 90 outside ABA set (N-RTN-1)
INV_REF_9 = "000418225"                  # area 000 / prefix 00 / no kw -> nothing fires (N-INV-1)
ACH_TRACE_15 = "213004929000137"         # 15-digit ACH trace -> routing len!=9, no cc/acct (N-RTN-2)

# ein negatives
EIN_INVALID_PREFIX = "07-3300449"        # prefix 07 in invalid set -> EIN rejects (occ_w2_06)
EIN_NONSHAPE = "099-2241-7"              # NON-EIN shape (C1) -> no candidate (N-EIN-1)
ACH_CO_ID = "1364419872"                 # "1" + 9-digit EIN; 10 digits -> no EIN; keep from phone kw

# itin negatives
ITIN_BAD_GROUP = "912-12-3344"           # group 12 out of ITIN range -> rejects (N-ITIN-1)
ITIN_NO_KW = "970-72-5518"               # valid ITIN shape, no itin/tin kw within +-8 -> not emitted
ITIN_BAD_SEP = "970-72 5518"             # dash-then-space -> backref \1 fails (N-ITIN-3)

# ssn negatives
SSN_WOOLWORTH = "078-05-1120"            # wallet/Woolworth -> SSNStructuralValidator Rule 6 hard reject
SSN_900 = "900-12-3456"                  # area 900 >= 900 -> SSN rejects; group 12 out of ITIN range
SSN_SSA_ADVERT = "987-65-4320"           # SSA advertising block, area 987 >= 900 -> rejects (C3 neighborhd)
ACCT_AS_PHONE = "4100773265"             # = STMT account; 10-digit NANP shape + phone kw -> phone wins

# dl / passport negatives
DL_TOO_LONG = "X44021855140037"          # 1L+14D (15 chars) > every dl_patterns row -> suppressed
PP_TOO_SHORT = "X123456"                 # 1L+6D (7 chars) matches no issuer row -> suppressed
PP_ALL_NUMERIC = "000123456"             # pure 9-digit -> passport capture needs a leading letter
PP_BAD_LEN = "X123004567"                # 1L+9D (10 chars) matches no 9-char issuer row; group 00 SSN-inv

# date negatives (bare dates -> suppressed on .financial label-anchored-only gate)
DATE_SIGN_0430 = "04/30/2026"            # application / authorization sign date
DATE_SIGN_0412 = "04/12/2026"            # 1040 signature date
DATE_EMP_START = "06/01/2019"            # employment start date
DATE_LICENSE_EXP = "08/19/2028"          # DL expiry
DATE_PP_ISSUE = "03/02/2021"             # passport issue
TAXYEAR_SPAN_DOT = "Jan. 1 - Dec. 31, 2025"   # tax-year span (T1040)
TAXYEAR_SPAN = "Jan 1 - Dec 31, 2025"         # tax-year span (W-2)

# phone negative
PHONE_CASE_NEG = "208-555-0144"          # negative-context "Case No." + no phone kw -> dropped

# ==================================================================================================
# 6. VEH .generic vehicle-collateral exhibit values
# ==================================================================================================
VEH_PLATE = "7XYZ842"                    # CA-style 1+3+3 plate, must-fire on .generic
VEH_VIN = "4S4BSANC1K3304412"            # 17-char VIN behind VIN: (not a plate label) -> MNF
VEH_TAG_NEG = "88KJ2"                    # plate label + negative-context "serial" -> dampened MNF
VEH_PLATE_FIN = "6ABC123"                # plate on the FINANCIAL URLA-B page -> doctype-gated MNF
