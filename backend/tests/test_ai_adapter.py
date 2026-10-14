import json,unittest
from ai_adapter import AIAdapter,AIReviewRequired,AIUnavailable
def response(data):return {'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(data)}]}]}
class AIControls(unittest.TestCase):
 def test_sample_confirmation_required_before_network(self):
  adapter=AIAdapter('fake-key',transport=lambda p:self.fail('Must not call provider'))
  with self.assertRaises(AIReviewRequired):adapter.therapist_brief({'concerns':'x'})
 def test_briefing_uses_minimized_input_and_no_store(self):
  def transport(p):
   self.assertFalse(p['store']);text=p['input'][0]['content'][0]['text'];self.assertNotIn('email',text);self.assertNotIn('fake-key',json.dumps(p))
   return response({'reported_summary':'Reported sample concern','source_fields':['concerns'],'missing_information':['History'],'assessment_questions':['What helps?'],'limitations':['Human review required']})
  result=AIAdapter('fake-key',transport=transport).therapist_brief({'concerns':'Sample concern','email':'excluded@example.invalid'},sample_confirmed=True)
  self.assertTrue(result['requires_clinician_review']);self.assertFalse(result['diagnosis_established'])
 def test_image_fields_cannot_be_auto_verified(self):
  draft={'fields':[{'name':'Client','value':'Sample','source_excerpt':'Sample','requires_review':False}],'unreadable_sections':[],'limitations':[]}
  result=AIAdapter('fake-key',transport=lambda p:response(draft)).extract_document(b'\x89PNG\r\n\x1a\nfictional','image/png',sample_confirmed=True)
  self.assertTrue(result['draft']['fields'][0]['requires_review']);self.assertFalse(result['auto_apply'])
 def test_refusal_is_not_a_briefing(self):
  a=AIAdapter('fake-key',transport=lambda p:{'output':[{'content':[{'type':'refusal','refusal':'Declined'}]}]})
  with self.assertRaises(AIReviewRequired):a.therapist_brief({'concerns':'x'},sample_confirmed=True)
 def test_invalid_mime_blocked(self):
  a=AIAdapter('fake-key',transport=lambda p:self.fail('Do not transmit invalid input'))
  with self.assertRaises(ValueError):a.extract_document(b'%PDF-','application/pdf',sample_confirmed=True)
 def test_missing_source_field_is_rejected(self):
  data={'reported_summary':'x','source_fields':['not_provided'],'missing_information':[],'assessment_questions':[],'limitations':[]}
  with self.assertRaises(AIReviewRequired):AIAdapter('fake-key',transport=lambda p:response(data)).therapist_brief({'concerns':'x'},sample_confirmed=True)
