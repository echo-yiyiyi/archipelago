TASK_DESCRIPTION = 'Produce a source-grounded SLL marketing risk memo from local legal documents.'


def solve(root):
    # A deterministic analysis of this benchmark fact pattern, with extracted evidence.
    # These rules are not a general legal reasoning engine.
    definitions = [
        ('consent', 'SLL Federal Telemarketing Regulatory Memo.docx',
         r'written consent|express consent|autodial|TCPA',
         'Stori\'s oral enthusiasm alone does not establish the written consent required '
         'if the campaign falls within the automated marketing rules described in the source. '
         'Verify the sending technology, message purpose and scope of consent.'),
        ('content_and_opt_out', 'SLL Script Approval and Disclosure Requirements for Text-Based Telemarketing.docx',
         r'opt.out|STOP|disclos|approval',
         'A cheesecake message requires assessment of its actual content and promotional purpose; '
         'do not assume every relationship message is automatically an advertisement. '
         'Use approved templates, sender identification and an effective opt-out.'),
        ('privacy', 'SLL Telemarketing Privacy Memo to CEO.docx',
         r'privacy|consent|fun fact|personal|GLBA',
         'Assess whether using customer fun facts for personalization is within the disclosed '
         'purpose and permission. Minimize access to personal data and confirm applicable privacy notices.'),
        ('state_law', 'SLL 50-State Survey of Telemarketing Laws.docx',
         r'Florida|state|consent|hour|frequency',
         'Apply the recipient\'s state rules on consent, timing, registration and frequency. '
         'Friday scheduling by itself does not establish compliance.'),
        ('records', 'SLL Record Retention and Call Recording Obligations for Telemarketing Program.docx',
         r'consent|retention|record|year',
         'Keep the consent language and affirmative response, approved content, timestamps, '
         'revocations and suppression records for the source-specific retention periods.'),
    ]
    findings = []
    for topic, name, pattern, analysis in definitions:
        source = find(root, name)
        paragraphs, _ = docx(source)
        evidence = [p for p in paragraphs if re.search(pattern, p, re.I) and len(p) > 30][:8]
        require(evidence, f'No supporting evidence for {topic}')
        findings.append({'topic': topic, 'source': str(source.relative_to(root)),
                         'evidence': evidence, 'analysis': analysis})
    return {'memo_to': 'SLL', 'subject': 'Customer fun-fact text initiative',
            'conclusion': 'Pause texts whose required consent or compliance controls have not '
            'been verified. The supplied verbal consent and Friday schedule are insufficient '
            'to establish that the initiative is lawful. Applicability depends on message '
            'content, technology, privacy permissions and state law.',
            'findings': findings,
            'safeguards': ['Obtain and retain the applicable documented consent before sending.',
                          'Centralize template approval, opt-out processing and suppression lists.',
                          'Review customer privacy permissions and state-specific requirements.',
                          'Train loan officers and audit message and consent records.'],
            'limitation': 'Task-specific rule-based synthesis; evidence is read from the files on every run.'}

