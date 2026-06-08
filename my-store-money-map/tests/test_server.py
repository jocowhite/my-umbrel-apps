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

    def test_current_n26_booking_date_export(self):
        raw = (
            '"Booking Date","Value Date","Partner Name","Partner Iban",Type,'
            '"Payment Reference","Account Name","Amount (EUR)","Original Amount",'
            '"Original Currency","Exchange Rate"\n'
            '2025-01-01,2024-12-31,"DB Vertrieb GmbH",DE123,Presentment,,'
            'Hauptkonto,-13.49,13.49,EUR,1\n'
        ).encode()
        source, rows = app.parse_transactions(raw, "auto")
        self.assertEqual(source, "n26")
        self.assertEqual(rows[0]["booked_on"], "2025-01-01")
        self.assertEqual(rows[0]["value_on"], "2024-12-31")
        self.assertEqual(rows[0]["payee"], "DB Vertrieb GmbH")
        self.assertEqual(rows[0]["iban"], "DE123")
        self.assertEqual(rows[0]["account"], "Hauptkonto")
        self.assertEqual(rows[0]["amount_cents"], -1349)

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

    def test_matching_rules_explain_priority_conflicts(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,DM Drogerie Stuttgart,Card,Einkauf,-25.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            transaction_id = conn.execute("SELECT id FROM transactions").fetchone()["id"]
        matches = app.matching_rules(transaction_id)
        self.assertEqual(matches[0]["name"], "Drogerie")
        self.assertEqual(matches[0]["category"], "Haushalt")
        self.assertEqual(matches[0]["priority"], 80)

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

    def test_dashboard_source_filter(self):
        sparkasse = (
            "Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag;Waehrung\n"
            "01.06.2026;Einkauf;REWE;-20,00;EUR\n"
        ).encode()
        n26 = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,CinemaxX,Card,Film,-15.00\n"
        ).encode()
        app.import_csv(sparkasse, "sparkasse", "sparkasse.csv")
        app.import_csv(n26, "n26", "n26.csv")
        self.assertEqual(app.dashboard("2026-06", "sparkasse")["totals"]["expenses"], 20)
        self.assertEqual(app.dashboard("2026-06", "n26")["totals"]["expenses"], 15)

    def test_personal_dashboard_nets_shared_household_income(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-01,Vermieter,Bank Transfer,Miete,-1000.00\n"
            "2026-06-03,Mitbewohner,Bank Transfer,Mietanteil,450.00\n"
            "2026-06-04,Arbeitgeber,Bank Transfer,Gehalt,2000.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute(
                "UPDATE transactions SET category='Wohnen', is_manual=1 WHERE payee IN ('Vermieter','Mitbewohner')"
            )
        gross = app.dashboard("2026-06", view="gross")
        personal = app.dashboard("2026-06", view="personal")
        self.assertEqual(gross["totals"]["income"], 2450)
        self.assertEqual(gross["totals"]["expenses"], 1000)
        self.assertEqual(personal["totals"]["income"], 2000)
        self.assertEqual(personal["totals"]["expenses"], 550)
        housing = next(row for row in personal["categories"] if row["category"] == "Wohnen")
        self.assertEqual(housing["amount"], 550)

    def test_shared_household_supports_cross_month_date_ranges(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2025-12-15,Vermieter,Bank Transfer,Miete,-1000.00\n"
            "2026-01-03,Mitbewohner,Bank Transfer,Mietanteil,450.00\n"
            "2026-01-10,Stadtwerke,Debit,Nebenkosten,-120.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute(
                "UPDATE transactions SET category='Wohnen', is_manual=1 WHERE payee IN ('Vermieter','Mitbewohner')"
            )
            conn.execute(
                "UPDATE transactions SET category='Haushalt', is_manual=1 WHERE payee='Stadtwerke'"
            )
        result = app.shared_household("2025-12-01", "2026-01-31")
        self.assertEqual(result["paid"], 1120)
        self.assertEqual(result["received"], 450)
        self.assertEqual(result["net"], 670)
        self.assertEqual(len(result["transactions"]), 3)

    def test_sankey_data_filters_and_includes_full_transaction_detail(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-05-31,Arbeitgeber,Bank Transfer,Gehalt,2000.00\n"
            "2026-06-02,REWE,Card,Einkauf,-25.00\n"
            "2026-06-03,CinemaxX,Card,Film,-15.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        result = app.sankey_data(
            "2026-06-01", "2026-06-30", ["n26"], ["Lebensmittel"]
        )
        self.assertEqual(result["summary"]["income"], 0)
        self.assertEqual(result["summary"]["expenses"], 25)
        self.assertEqual(result["summary"]["count"], 1)
        self.assertEqual(result["transactions"][0]["counterparty"], "REWE")
        self.assertEqual(result["transactions"][0]["account_label"], "N26")
        self.assertEqual(result["transactions"][0]["color"], "#25b986")

    def test_sankey_transfers_are_optional(self):
        sparkasse = (
            "Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag;Waehrung\n"
            "01.06.2026;Umbuchung;N26;-100,00;EUR\n"
        ).encode()
        n26 = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Test User,Bank Transfer,Umbuchung,100.00\n"
        ).encode()
        app.import_csv(sparkasse, "sparkasse", "sparkasse.csv")
        app.import_csv(n26, "n26", "n26.csv")
        hidden = app.sankey_data("2026-06-01", "2026-06-30")
        visible = app.sankey_data(
            "2026-06-01", "2026-06-30", include_transfers=True
        )
        self.assertEqual(hidden["summary"]["count"], 0)
        self.assertEqual(visible["summary"]["count"], 2)
        self.assertEqual(visible["summary"]["transfers"], 100)

    def test_outlays_are_balanced_and_excluded_from_dashboard(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Restaurant,Card,Teamessen,-80.00\n"
            "2026-06-04,Kollege,Bank Transfer,Erstattung,50.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute("UPDATE transactions SET category='Auslagen', is_manual=1")
        result = app.outlays()
        dashboard = app.dashboard("2026-06")
        self.assertEqual(result["paid"], 80)
        self.assertEqual(result["reimbursed"], 50)
        self.assertEqual(result["open"], 30)
        self.assertEqual(dashboard["totals"]["expenses"], 0)
        self.assertEqual(dashboard["totals"]["income"], 0)

    def test_equal_outlay_and_reimbursement_are_marked_settled(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,Hotel,Card,Auslage,-120.00\n"
            "2026-06-04,Kollege,Bank Transfer,Erstattung,120.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute("UPDATE transactions SET category='Auslagen', is_manual=1")
        statuses = {row["outlay_status"] for row in app.outlays()["transactions"]}
        self.assertEqual(statuses, {"settled"})

    def test_category_usage_and_disable(self):
        raw = (
            "Date,Payee,Transaction type,Payment reference,Amount (EUR)\n"
            "2026-06-02,ATM,Cash Withdrawal,Bargeld,-40.00\n"
        ).encode()
        app.import_csv(raw, "n26", "n26.csv")
        with app.connect() as conn:
            conn.execute("UPDATE transactions SET category='Bargeld', is_manual=1")
        usage = {row["name"]: row for row in app.category_usage()}
        self.assertEqual(usage["Bargeld"]["usage_count"], 1)
        app.disable_category("Bargeld")
        with app.connect() as conn:
            transaction = conn.execute("SELECT category FROM transactions").fetchone()
            enabled = conn.execute(
                "SELECT enabled FROM categories WHERE name='Bargeld'"
            ).fetchone()["enabled"]
        self.assertEqual(transaction["category"], "Sonstiges")
        self.assertEqual(enabled, 0)


if __name__ == "__main__":
    unittest.main()
