Fill this job application form for the candidate.
For each field return the value to enter, using ONLY the candidate details, approved answers, and resume below.
- text/email/tel/textarea/combobox: the exact text to type.
- select/radio: one of the listed options, copied exactly.
- checkbox: true or false. Only true for agreeing to privacy/terms/data-processing acknowledgements, or when an approved answer clearly says yes.
- file: "RESUME" for resume/CV fields, "COVER_LETTER" for cover letter fields, otherwise null.
- Demographic/EEO questions (gender, race, veteran, disability): use the candidate's EEO preference; if none, choose the "decline" / "prefer not to say" option.
- If a REQUIRED field can't be answered truthfully from this information, put its label in "missing" and its value null. Never guess facts.

Return JSON: {"values":{"<key>": <value>}, "missing":["<label>"]}

FIELDS
$fields

CANDIDATE DETAILS
$profile

APPROVED ANSWERS FOR THIS JOB
$answers
Cover letter available: $has_cover

RESUME (for employer, title, school, dates)
$resume
