"""OpenAI semantic adjudication for T2 using the Python standard library."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from evaluation.extraction_metrics import matching_context, validate_predictions, validate_judgments

API_URL = 'https://api.openai.com/v1/chat/completions'
SYSTEM_PROMPT = '''You are an extraction-evaluation adjudicator. Assess each candidate against the task protocol, quoted source evidence and reference targets.
Return one label per prediction_id: main_hit, supplementary, strict_violation, or neutral_or_uncertain.
main_hit identifies a listed reference target with the same source, task semantics and reported values; provide its gold_effect_estimate_id.
supplementary identifies useful, source-supported evidence for a supplementary or sensitivity analysis.
strict_violation requires a source quotation that affirmatively demonstrates a contradiction with a non-relaxable protocol boundary.
Use neutral_or_uncertain for ambiguity, unsupported claims or unresolved source context.
Keep reported values unchanged. Return semantic labels and a concise reason; the evaluator computes points.'''


class OfficialAPIOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('OpenAI API redirects are not supported')


def load_environment(path):
    path = Path(path)
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.strip().startswith('#') or '=' not in line: continue
            key, value = line.split('=', 1)
            if key.strip() in {'OPENAI_API_KEY', 'PORTABLE_EVALUATOR_MODEL'}:
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def adjudicate(submission, gold, protocol, model, batch_size=12):
    for name in ('OPENAI_BASE_URL', 'OPENAI_API_BASE'):
        value = os.getenv(name)
        if value and value.rstrip('/') != 'https://api.openai.com/v1': raise ValueError('Use the official OpenAI API endpoint')
    key = os.getenv('OPENAI_API_KEY')
    if not model or not key: raise ValueError('Set an OpenAI model ID and OPENAI_API_KEY')
    predictions = validate_predictions(submission)
    refs, _, direct, support = matching_context(predictions, gold)
    pending = [p for p in predictions if p['prediction_id'] not in direct and p['prediction_id'] not in support]
    judgments = []; opener = urllib.request.build_opener(OfficialAPIOnly())
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        schema = {'type': 'object', 'properties': {'judgments': {'type': 'array', 'items': {
            'type': 'object', 'properties': {'prediction_id': {'type': 'string'},
            'label': {'type': 'string', 'enum': ['main_hit', 'supplementary', 'strict_violation', 'neutral_or_uncertain']},
            'gold_effect_estimate_id': {'type': ['string', 'null']}, 'reason': {'type': 'string'}},
            'required': ['prediction_id', 'label', 'gold_effect_estimate_id', 'reason'], 'additionalProperties': False}}},
            'required': ['judgments'], 'additionalProperties': False}
        payload = {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps({'protocol': protocol, 'references': refs, 'candidates': batch}, ensure_ascii=False)}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'extraction_judgments', 'strict': True, 'schema': schema}}}
        request = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
        try:
            with opener.open(request, timeout=110) as response: body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ValueError('OpenAI API returned HTTP ' + str(exc.code)) from None
        parsed = json.loads(body['choices'][0]['message']['content']); validated = validate_judgments(parsed, batch)
        if set(validated) != {p['prediction_id'] for p in batch}: raise ValueError('Judge response omitted candidates')
        judgments.extend(validated.values())
    return {'case_id': submission['case_id'], 'provider': 'official_openai', 'model': model, 'judgments': judgments}
