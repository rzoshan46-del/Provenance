import os
from pathlib import Path
os.environ['PROVENANCE_LLM'] = 'canned'
os.environ['PROVENANCE_DB'] = 'data/smoke_debug.db'
smoke_db = Path('data/smoke_debug.db')
if smoke_db.exists():
    smoke_db.unlink()
for suffix in ['-journal','-shm','-wal']:
    extra = Path('data/smoke_debug.db' + suffix)
    if extra.exists():
        extra.unlink()

from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, query_all, query_one, execute
from app.seed import seed_users, seed_projects

init_db(); seed_users(); seed_projects()

# helper

def client_for(name):
    row = query_one("SELECT id FROM users WHERE name = ?", (name,))
    c = TestClient(app, follow_redirects=True)
    c.cookies.set('persona_id', str(row['id']))
    return c

sponsor_client = client_for('Meera Rao')
arvind_client = client_for('Arvind Nair')
ananya_client = client_for('Ananya')
rahul_client = client_for('Rahul')

# prepare project A and B
res_p_inta = sponsor_client.post('/api/projects', data={'title':'Integrity Test Project A','public_summary':'s','confidential_brief':'b','sensitivity_label':'confidential','engagement_model':'funded'})
p_inta_id = res_p_inta.json()['project_id']
for cl in [arvind_client, ananya_client, rahul_client]:
    cl.post(f'/api/projects/{p_inta_id}/join', data={'accept_charter':'1','ack_engagement_model':'1'})
res_m_inta = sponsor_client.post(f'/api/projects/{p_inta_id}/milestones', json={'title':'M1','deliverables':'d','acceptance_criteria':'c','amount_inr':100000})
m_inta_id = res_m_inta.json()['id']
sponsor_client.post(f'/api/milestones/{m_inta_id}/fund')
text = 'Rigorous diagnostic annotation guidelines establish standardised protocols for expert ophthalmologists categorising fundus lesions, defining unambiguous criteria for identifying microaneurysms, hard exudates, cotton wool spots, and intraretinal microvascular abnormalities across distributed clinical datasets.'
res_orig = ananya_client.post(f'/api/milestones/{m_inta_id}/contributions', json={'title':'Ananya Quantum Baseline','text':text,'ai_declaration':'human'})
print('orig status', res_orig.status_code, res_orig.json())
res_dup = rahul_client.post(f'/api/milestones/{m_inta_id}/contributions', json={'title':'Rahul Plagiarised Copy 130','text':text,'ai_declaration':'human'})
print('dup status', res_dup.status_code, res_dup.json())
res_ms_inta = arvind_client.get(f'/projects/{p_inta_id}/milestones')
print('html_inta contains FLAGGED?', 'FLAGGED' in res_ms_inta.text)
print('html_inta contains Integrity Report?', 'Integrity Report' in res_ms_inta.text)
print('html_inta contains Ananya Quantum Baseline?', 'Ananya Quantum Baseline' in res_ms_inta.text)
from app.integrity.similarity import tokenize
first_phrase = ' '.join(tokenize(text)[:3])
print('first phrase', first_phrase)
print('first phrase in html?', first_phrase in res_ms_inta.text)

res_p_intb = sponsor_client.post('/api/projects', data={'title':'Integrity Test Project B','public_summary':'Summary B','confidential_brief':'Brief B','sensitivity_label':'confidential','engagement_model':'funded'})
p_intb_id = res_p_intb.json()['project_id']
rahul_client.post(f'/api/projects/{p_intb_id}/join', data={'accept_charter':'1','ack_engagement_model':'1'})
arvind_client.post(f'/api/projects/{p_intb_id}/join', data={'accept_charter':'1','ack_engagement_model':'1'})
res_m_intb = sponsor_client.post(f'/api/projects/{p_intb_id}/milestones', json={'title':'Milestone B1','deliverables':'d','acceptance_criteria':'c','amount_inr':50000})
m_intb_id = res_m_intb.json()['id']
sponsor_client.post(f'/api/milestones/{m_intb_id}/fund')
res_cross = rahul_client.post(f'/api/milestones/{m_intb_id}/contributions', json={'title':'Rahul Cross Project Copy','text':text,'ai_declaration':'human'})
print('cross status', res_cross.status_code, res_cross.text)
res_ms_intb = arvind_client.get(f'/projects/{p_intb_id}/milestones')
print('html_intb contains details hidden?', 'details hidden' in res_ms_intb.text)
print('html_intb contains Ananya Original Work?', 'Ananya Original Work' in res_ms_intb.text)
print('text_ananya_orig in html_intb?', text in res_ms_intb.text)
print(res_ms_intb.text[:2000])
