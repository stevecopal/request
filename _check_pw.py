from django.test import Client

c = Client()
for u in ("ETU001", "ENS001"):
    pw = f"{u}Univ!2026"
    try:
        r = c.post("/accounts/login/", {"matricule": u, "password": pw})
        print(u, r.status_code, r.json())
    except Exception as e:
        import traceback
        print(u, "EXCEPTION:", type(e).__name__, e)
        traceback.print_exc()
    c.logout()
r = c.post("/accounts/login/", {"matricule": "ETU001", "password": "faux"})
print("WRONG", r.status_code, r.json())

