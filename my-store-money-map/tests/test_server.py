import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


SERVER = Path(__file__).parents[1] / "app" / "server.py"
spec = importlib.util.spec_from_file_location("money_map_server", SERVER)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class MoneyMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DATA_DIR = Path(self.tmp.name)
        app.DB_PATH = app.DATA_DIR / "test.sqlite3"
        app.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_sparkasse_import_and_rules(self):
        raw = (
            "Auftragskonto;Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;"
            "Beguenstigter/Zahlungspflichtiger;Kontonummer/IBAN;Betrag;Waehrung\n"
            "DE111;03.06.2026;03.06.2026;Lastschrift;Einkauf;REWE Stuttgart;DE222;-42,17;EUR\n"
        ).encode()
        result = app.import_csv(raw, "auto", "sparkasse.csv")
        self.assertEqual(result["source"], "sparkasse")
        self.assertEqual(result["new"], 1)
        with app.connect() as conn:
            row = conn.execute("SELECT * FROM transactions").fetchone()
        self.assertEqual(row["amount_cents"], -4217)
        self.assertEqual(row["category"], "Lebensmittel")

    def test_n26_and_paypal_detection(self):
        n26 = (
            "Date,Payee,Account number,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-04,CinemaxX,,Mastercard,Film,-15.00\n"
        ).encode()
        source, rows = app.parse_transactions(n26, "auto")
        self.assertEqual(source, "n26")
        self.assertEqual(rows[0]["amount_cents"], -1500)

        paypal = (
            "Datum;Uhrzeit;Name;Typ;Status;Waehrung;Brutto;Gebuehr;Netto;Transaktionscode\n"
            "05.06.2026;12:00:00;Spotify;Zahlung;Abgeschlossen;EUR;-10,99;0,00;-10,99;ABC\n"
        ).encode()
        source, rows = app.parse_transactions(paypal, "auto")
        self.assertEqual(source, "paypal")
        self.assertEqual(rows[0]["amount_cents"], -1099)

    def test_duplicate_and_transfer_reconciliation(self):
        sparkasse = (
            "Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag;Waehrung\n"
            "01.06.2026;Umbuchung;N26;-100,00;EUR\n"
        ).encode()
        n26 = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Test User,Bank Transfer,Umbuchung,100.00\n"
        ).encode()
        first = app.import_csv(sparkasse, "sparkasse", "a.csv")
        duplicate = app.import_csv(sparkasse, "sparkasse", "a.csv")
        second = app.import_csv(n26, "n26", "b.csv")
        self.assertEqual(first["new"], 1)
        self.assertEqual(duplicate["duplicates"], 1)
        self.assertEqual(second["transfer_pairs"], 1)
        with app.connect() as conn:
            rows = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
        self.assertTrue(all(row["is_transfer"] for row in rows))
        self.assertTrue(all(row["category"] == "Interner Transfer" for row in rows))

    def test_custom_keyword_rule_recategorizes(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Special Vendor,Card,Sommerfest,-55.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO rules(name,match_type,pattern,category,expense_type,priority) VALUES(?,?,?,?,?,?)",
                ("Festival", "keyword", "sommerfest", "Reisen & Festivals", "variable", 100),
            )
            app.recategorize(conn)
            row = conn.execute("SELECT * FROM transactions").fetchone()
        self.assertEqual(row["category"], "Reisen & Festivals")

    def test_investments_are_tracked_separately_from_expenses(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Trade Republic,Bank Transfer,ETF Sparplan,-100.00\n"
            "2026-06-03,REWE,Card,Einkauf,-25.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            transaction_id = conn.execute(
                "SELECT id FROM transactions WHERE payee='Trade Republic'"
            ).fetchone()["id"]
            conn.execute(
                "UPDATE transactions SET category='Investieren · MSCI World', is_manual=1 WHERE id=?",
                (transaction_id,),
            )
        dashboard = app.dashboard("2026-06")
        investments = app.investments()
        self.assertEqual(dashboard["totals"]["expenses"], 25)
        self.assertEqual(investments["invested"], 100)
        self.assertEqual(investments["categories"][0]["label"], "MSCI World")


if __name__ == "__main__":
    unittest.main()
