# Veritas data dictionary

_Generated from the live schema (24 Oct 2026); regenerate with `python docs/make_docs.py`._

## anchors

| column | type | null | default | key |
|---|---|---|---|---|
| anchor_id | integer | no |  | PK |
| batch_id | integer | no |  | FK to merkle_batches.batch_id |
| anchor_type | text | no |  |  |
| anchor_ref | text | no |  |  |
| anchored_at | timestamp with time zone | no | now() |  |
- check: `CHECK ((anchor_type = ANY (ARRAY['immudb'::text, 'git'::text, 'file'::text])))`

## anomaly_alerts

| column | type | null | default | key |
|---|---|---|---|---|
| alert_id | integer | no |  | PK |
| revision_id | bigint | no |  | FK to mark_revisions.revision_id |
| reviewed_by | integer | yes |  | FK to faculty.user_id |
| model_name | text | no |  |  |
| score | real | no |  |  |
| top_features | text | yes |  |  |
| status | text | no | 'open'::text |  |
| created_at | timestamp with time zone | no | now() |  |
| reviewed_at | timestamp with time zone | yes |  |  |
- check: `CHECK ((status = ANY (ARRAY['open'::text, 'confirmed'::text, 'dismissed'::text])))`

## app_credentials

| column | type | null | default | key |
|---|---|---|---|---|
| user_id | integer | no |  | PK |
| password_hash | text | no |  |  |

## assessments

| column | type | null | default | key |
|---|---|---|---|---|
| course_id | integer | no |  | PK |
| type | text | no |  | PK |
| max_marks | numeric | no |  |  |
| freeze_at | timestamp with time zone | no |  |  |
- check: `CHECK ((type = ANY (ARRAY['CIE-1'::text, 'CIE-2'::text, 'SEE'::text])))`
- check: `CHECK ((max_marks > (0)::numeric))`

## certificate_documents

| column | type | null | default | key |
|---|---|---|---|---|
| cert_id | uuid | no |  | PK |
| mime | text | no | 'application/pdf'::text |  |
| doc | bytea | no |  |  |
| created_at | timestamp with time zone | no | now() |  |

## certificates

| column | type | null | default | key |
|---|---|---|---|---|
| cert_id | uuid | no | gen_random_uuid() | PK |
| student_id | integer | no |  | FK to students.user_id |
| issued_by | integer | no |  | FK to faculty.user_id |
| cert_type | text | no |  |  |
| doc_hash | character | no |  |  |
| salt | character | no |  |  |
| status | text | no | 'valid'::text |  |
| issued_at | timestamp with time zone | no | now() |  |
| revoked_at | timestamp with time zone | yes |  |  |
- check: `CHECK ((status = ANY (ARRAY['valid'::text, 'revoked'::text])))`
- check: `CHECK (((status = 'valid'::text) = (revoked_at IS NULL)))`

## change_requests

| column | type | null | default | key |
|---|---|---|---|---|
| request_id | integer | no |  | PK |
| mark_id | integer | no |  | FK to marks.mark_id |
| requested_by | integer | no |  | FK to faculty.user_id |
| approved_by | integer | yes |  | FK to faculty.user_id |
| proposed_value | numeric | no |  |  |
| reason | text | no |  |  |
| status | text | no | 'pending'::text |  |
| requested_at | timestamp with time zone | no | now() |  |
| decided_at | timestamp with time zone | yes |  |  |
- check: `CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'applied'::text])))`
- check: `CHECK (((approved_by IS NULL) OR (approved_by <> requested_by)))`
- check: `CHECK ((((status = 'pending'::text) AND (approved_by IS NULL) AND (decided_at IS NULL)) OR ((status <> 'pending'::text) AND (approved_by IS NOT NULL) AND (decid`
- check: `CHECK ((proposed_value >= (0)::numeric))`
- check: `CHECK ((length(btrim(reason)) >= 5))`

## courses

| column | type | null | default | key |
|---|---|---|---|---|
| course_id | integer | no |  | PK |
| course_code | text | no |  |  |
| title | text | no |  |  |
| credits | smallint | no |  |  |
| semester | smallint | no |  |  |
| faculty_id | integer | no |  | FK to faculty.user_id |
| institution_id | integer | no | 1 | FK to institutions.institution_id |

- unique: `UNIQUE (course_code, semester)`
- check: `CHECK (((semester >= 1) AND (semester <= 8)))`
- check: `CHECK (((credits >= 1) AND (credits <= 6)))`

## faculty

| column | type | null | default | key |
|---|---|---|---|---|
| user_id | integer | no |  | PK |
| employee_id | text | no |  |  |
| department | text | no |  |  |
| can_approve | boolean | no | false |  |

- unique: `UNIQUE (employee_id)`

## institutions

| column | type | null | default | key |
|---|---|---|---|---|
| institution_id | integer | no |  | PK |
| slug | text | no |  |  |
| name | text | no |  |  |

- unique: `UNIQUE (slug)`
- check: `CHECK ((slug ~ '^[a-z0-9-]+$'::text))`

## integrity_runs

| column | type | null | default | key |
|---|---|---|---|---|
| run_id | bigint | no |  | PK |
| kind | text | no |  |  |
| ok | boolean | no |  |  |
| detail | jsonb | no | '{}'::jsonb |  |
| started_at | timestamp with time zone | no | now() |  |
- check: `CHECK ((kind = ANY (ARRAY['verify'::text, 'seal'::text, 'anchor'::text, 'score'::text])))`

## login_attempts

| column | type | null | default | key |
|---|---|---|---|---|
| attempt_id | bigint | no |  | PK |
| email | text | no |  |  |
| ip | text | yes |  |  |
| ok | boolean | no |  |  |
| at | timestamp with time zone | no | now() |  |

## mark_revisions

| column | type | null | default | key |
|---|---|---|---|---|
| revision_id | bigint | no |  | PK |
| mark_id | integer | no |  | FK to marks.mark_id |
| course_id | integer | no |  | FK to courses.course_id |
| seq | integer | no |  |  |
| request_id | integer | yes |  | FK to change_requests.request_id |
| prev_revision_id | bigint | yes |  | FK to mark_revisions.revision_id |
| old_value | numeric | yes |  |  |
| new_value | numeric | no |  |  |
| changed_by | integer | no |  | FK to faculty.user_id |
| reason | text | no |  |  |
| changed_at | timestamp with time zone | no |  |  |
| prev_hash | character | no |  |  |
| row_hash | character | no |  |  |

- unique: `UNIQUE (course_id, seq)`
- check: `CHECK ((seq >= 1))`

## marks

| column | type | null | default | key |
|---|---|---|---|---|
| mark_id | integer | no |  | PK |
| student_id | integer | no |  | FK to students.user_id |
| course_id | integer | no |  | FK to assessments.course_id |
| assessment_type | text | no |  | FK to assessments.course_id |
| current_value | numeric | yes |  |  |
| version | integer | no | 0 |  |
| updated_at | timestamp with time zone | yes |  |  |

- unique: `UNIQUE (student_id, course_id, assessment_type)`
- check: `CHECK ((current_value >= (0)::numeric))`

## merkle_batches

| column | type | null | default | key |
|---|---|---|---|---|
| batch_id | integer | no |  | PK |
| course_id | integer | no |  | FK to courses.course_id |
| seq_from | integer | no |  |  |
| seq_to | integer | no |  |  |
| merkle_root | character | no |  |  |
| created_at | timestamp with time zone | no | now() |  |

- unique: `UNIQUE (course_id, seq_from)`
- check: `CHECK ((seq_to >= seq_from))`

## notifications

| column | type | null | default | key |
|---|---|---|---|---|
| notification_id | bigint | no |  | PK |
| user_id | integer | no |  | FK to users.user_id |
| kind | text | no |  |  |
| message | text | no |  |  |
| link | text | yes |  |  |
| created_at | timestamp with time zone | no | now() |  |
| read_at | timestamp with time zone | yes |  |  |

## students

| column | type | null | default | key |
|---|---|---|---|---|
| user_id | integer | no |  | PK |
| usn | text | no |  |  |
| branch | text | no |  |  |
| semester | smallint | no |  |  |

- unique: `UNIQUE (usn)`
- check: `CHECK (((semester >= 1) AND (semester <= 8)))`

## users

| column | type | null | default | key |
|---|---|---|---|---|
| user_id | integer | no |  | PK |
| name | text | no |  |  |
| email | text | no |  |  |
| role | text | no |  |  |
| created_at | timestamp with time zone | no | now() |  |
| institution_id | integer | no | 1 | FK to institutions.institution_id |

- unique: `UNIQUE (email)`
- check: `CHECK ((role = ANY (ARRAY['student'::text, 'faculty'::text, 'admin'::text])))`
