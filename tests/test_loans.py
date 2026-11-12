import os
from uuid import uuid4
os.environ['DATABASE_URL'] = 'sqlite:////tmp/loan-test.db'
import httpx
from fastapi.testclient import TestClient
from app import main

def test_pending_request_recovers_after_timeout(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    calls=[]
    def remote(method, url, **kwargs):
        calls.append((method,url))
        if len(calls)==1:
            raise httpx.ReadTimeout('response lost after reservation')
        return httpx.Response(200,json={'released':method=='DELETE'})
    monkeypatch.setattr(main.httpx,'request',remote)
    body={'loan_id':str(uuid4()),'equipment_id':str(uuid4()),'borrower_id':'student'}
    with TestClient(main.app) as client:
        assert client.post('/loans',json=body).status_code==503
        assert client.get('/loans/'+body['loan_id']).json()['status']=='PENDING'
        assert client.post('/loans',json=body).json()['status']=='ACTIVE'
        assert calls[0]==calls[1]  # Same remote reservation ID on retry.
        assert client.post('/loans',json=body).json()['status']=='ACTIVE'
        assert len(calls)==2
        assert client.post('/loans',json={**body,'borrower_id':'different'}).status_code==409
        assert client.post('/loans/'+body['loan_id']+'/return').json()['status']=='RETURNED'
        assert client.post('/loans/'+body['loan_id']+'/return').json()['status']=='RETURNED'
        assert len(calls)==3

def test_rejected_loan_does_not_repeat_remote_request(monkeypatch):
    main.Base.metadata.drop_all(main.engine)
    calls=[]
    def remote(method,url,**kwargs):
        calls.append(url)
        return httpx.Response(409,json={'detail':'Equipment unavailable'})
    monkeypatch.setattr(main.httpx,'request',remote)
    body={'loan_id':str(uuid4()),'equipment_id':str(uuid4()),'borrower_id':'student'}
    with TestClient(main.app) as client:
        assert client.post('/loans',json=body).status_code==409
        assert client.post('/loans',json=body).status_code==409
        assert len(calls)==1
        assert client.get('/loans/'+body['loan_id']).json()['status']=='REJECTED'
        assert client.post('/loans/'+body['loan_id']+'/return').status_code==409
