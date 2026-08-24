#!/usr/bin/env python3
"""Mock test for citescan/stripe/create-payment-link.py.

Stubs the `stripe` module and /root/stripe.env + /opt/data/citescan-links.json
paths, then runs the create / status / activate flows and asserts:
  - 3 distinct payment links created
  - amounts 2900 / 3900 / 4900 cents EUR
  - every link created with active=False (pending activation)
  - links JSON written with status pending_activation + payment_link_ids
  - activate mode refuses without the exact gate phrase
  - activate mode flips active=True and status=active after the gate
"""
import importlib.util
import io
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

SCRIPT = str(Path(__file__).resolve().parent / "create-payment-link.py")
tmp = Path(tempfile.mkdtemp(prefix="stripe-mock-"))
links_json = tmp / "citescan-links.json"
stripe_env = tmp / "stripe.env"
stripe_env.write_text("STRIPE_RESTRICTED_KEY=rk_live_MOCK\n")

# ---- stub stripe module -------------------------------------------------
created_links = {}


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Product:
    _n = 0

    @classmethod
    def create(cls, **kw):
        cls._n += 1
        return _Obj(id=f"prod_mock{cls._n}", **kw)


class Price:
    created = []

    @classmethod
    def create(cls, **kw):
        cls.created.append(kw)
        return _Obj(id=f"price_mock{len(cls.created)}", **kw)


class PaymentLink:
    created = []

    @classmethod
    def create(cls, **kw):
        cls.created.append(kw)
        n = len(cls.created)
        link = _Obj(id=f"plink_mock{n}",
                    url=f"https://buy.stripe.com/mock{n}",
                    active=kw.get("active", True))
        created_links[link.id] = link
        return link

    @classmethod
    def update(cls, lid, **kw):
        for k, v in kw.items():
            setattr(created_links[lid], k, v)
        return created_links[lid]


fake_stripe = types.ModuleType("stripe")
fake_stripe.Product = Product
fake_stripe.Price = Price
fake_stripe.PaymentLink = PaymentLink
fake_stripe.api_key = None
sys.modules["stripe"] = fake_stripe

# ---- load the script as a module ---------------------------------------
spec = importlib.util.spec_from_file_location("cpl", SCRIPT)
cpl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpl)
cpl.STRIPE_ENV = stripe_env
cpl.LINKS_JSON = links_json

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- create flow ---------------------------------------------------------
with mock.patch("builtins.input", return_value="CREER-INACTIFS"):
    with mock.patch.object(sys, "argv", ["cpl", "create"]):
        cpl.main()

check("3 payment links created", len(PaymentLink.created) == 3)
check("amounts are 2900/3900/4900 EUR cents",
      [p["unit_amount"] for p in Price.created] == [2900, 3900, 4900]
      and all(p["currency"] == "eur" for p in Price.created))
check("ALL links created with active=False (pending activation)",
      all(c.get("active") is False for c in PaymentLink.created))
check("3 distinct URLs",
      len({l.url for l in created_links.values()}) == 3)

data = json.loads(links_json.read_text())
check("json status=pending_activation", data.get("status") == "pending_activation")
check("json has 3 links + 3 payment_link_ids",
      len(data["links"]) == 3 and len(data["payment_link_ids"]) == 3)
check("json poller format [audit, label, eur]",
      all(v[0] == "audit" and v[2] in (29, 39, 49) for v in data["links"].values()))

# idempotence: second create must refuse
try:
    with mock.patch.object(sys, "argv", ["cpl", "create"]):
        cpl.main()
    check("second create refused", False)
except SystemExit:
    check("second create refused (no duplicates)", True)

# ---- activate flow: wrong gate ------------------------------------------
before = [l.active for l in created_links.values()]
try:
    with mock.patch("builtins.input", return_value="oui"):
        with mock.patch.object(sys, "argv", ["cpl", "activate"]):
            cpl.main()
    check("activate without gate exits", False)
except SystemExit:
    pass
check("links still inactive after wrong gate phrase",
      all(l.active is False for l in created_links.values()))
check("status still pending_activation",
      json.loads(links_json.read_text())["status"] == "pending_activation")

# ---- activate flow: correct gate ----------------------------------------
with mock.patch("builtins.input", return_value="OUI-FRANCK-A-VALIDE"):
    with mock.patch.object(sys, "argv", ["cpl", "activate"]):
        cpl.main()
check("all 3 links active after gate",
      all(l.active is True for l in created_links.values()))
check("json status=active",
      json.loads(links_json.read_text())["status"] == "active")

# ---- status mode ---------------------------------------------------------
buf = io.StringIO()
with mock.patch.object(sys, "argv", ["cpl", "status"]):
    with mock.patch("sys.stdout", buf):
        cpl.main()
out = buf.getvalue()
check("status lists 29/39/49", all(f"{e} €" in out for e in (29, 39, 49)))

print()
print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
