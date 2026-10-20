"""Tests du service d'import ETL (data_importer)."""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import Department, Faculty, Student, Teacher
from accounts.services import matricules
from accounts.tests.factories import make_university
from core_scolarite.services.data_importer import ImportValidationError, import_users

HEADER = "MATRICULE,NOM,PRENOM,EMAIL,FACULTE,DEPARTEMENT"
YEAR = f"{matricules.registration_year() % 100:02d}"


def m(number: int, segment: str = "SCI") -> str:
    """Matricule officiel pour les tests : CM-UDS-26SCI0001."""
    return f"CM-UDS-{YEAR}{segment}{number:04d}"


def csv_upload(*rows, header=HEADER):
    content = "\n".join([header, *rows])
    return SimpleUploadedFile("etudiants.csv", content.encode("utf-8"), content_type="text/csv")


class ImporterValidationTests(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(
            university=self.university, name="Sciences", code="SCI"
        )
        self.department = Department.objects.create(
            faculty=self.faculty, name="Informatique"
        )

    def test_missing_header_raises(self):
        upload = csv_upload(
            f"{m(1)},Doe,John,a@b.c,Sciences,Informatique", header="MATRICULE,NOM,PRENOM"
        )
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertIn("EMAIL", ctx.exception.message)

    def test_successful_import_creates_students(self):
        upload = csv_upload(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            f"{m(2)},Roe,Jane,jane@univ.cm,Sciences,Informatique",
        )
        count = import_users(upload, entity="students", university=self.university)
        self.assertEqual(count, 2)
        student = Student.objects.get(registration_number=m(1))
        self.assertTrue(student.is_onboarded)
        self.assertTrue(User.objects.filter(username=m(1)).exists())

    def test_imported_accounts_start_inactive(self):
        """Aucun accès avant la première connexion (lien à usage unique)."""
        upload = csv_upload(f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique")
        import_users(upload, entity="students", university=self.university)
        user = User.objects.get(username=m(1))
        self.assertFalse(user.is_active)

    def test_unknown_faculty_reports_line_number(self):
        upload = csv_upload(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            f"{m(2)},Roe,Jane,jane@univ.cm,INEXISTANTE,Informatique",
        )
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertEqual(ctx.exception.errors[0]["line"], 3)

    def test_department_not_in_faculty_rejected(self):
        upload = csv_upload(f"{m(1)},Doe,John,john@univ.cm,Sciences,Histoire")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)

    def test_rollback_is_total(self):
        """Un fichier valide + une ligne cassée ⇒ 0 enregistrement."""
        upload = csv_upload(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            f"{m(2)},Roe,Jane,jane@univ.cm,Sciences,Informatique",
            f"{m(3)},Bad,Row,row@univ.cm,Sciences,Inexistant",
        )
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(User.objects.filter(username__in=[m(1), m(2)]).count(), 0)

    def test_duplicate_matricule_in_file_rejected(self):
        upload = csv_upload(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            f"{m(1)},Roe,Jane,jane@univ.cm,Sciences,Informatique",
        )
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)

    def test_duplicate_email_in_file_rejected(self):
        upload = csv_upload(
            f"{m(1)},Doe,John,same@univ.cm,Sciences,Informatique",
            f"{m(2)},Roe,Jane,SAME@univ.cm,Sciences,Informatique",
        )
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertTrue(any("EMAIL" in e["message"] for e in ctx.exception.errors))

    def test_duplicate_email_in_database_rejected(self):
        User.objects.create_user(username="OLD001", email="deja@univ.cm", password="x")
        upload = csv_upload(f"{m(1)},Doe,John,DEJA@univ.cm,Sciences,Informatique")
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertTrue(
            any("EMAIL" in e["message"] for e in ctx.exception.errors + ctx.exception.duplicates)
            or any("EMAIL" in d["reason"] for d in ctx.exception.duplicates)
        )

    def test_invalid_matricule_format_rejected(self):
        upload = csv_upload("M1,Doe,John,john@univ.cm,Sciences,Informatique")
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertTrue(any("MATRICULE" in e["message"] for e in ctx.exception.errors))

    def test_matricule_incoherent_with_faculty_rejected(self):
        """Un matricule portant le code d'une autre faculté est refusé."""
        other = Faculty.objects.create(university=self.university, name="Lettres", code="LET")
        Department.objects.create(faculty=other, name="Histoire")
        upload = csv_upload(f"{m(1, 'LET')},Doe,John,john@univ.cm,Sciences,Informatique")
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertTrue(
            any("faculté" in e["message"].lower() for e in ctx.exception.errors)
        )

    def test_teacher_import_uses_teacher_segment(self):
        upload = csv_upload(
            f"{m(1, 'ENS')},Doe,John,t@univ.cm,Sciences,Informatique",
            header=HEADER,
        )
        count = import_users(upload, entity="teachers", university=self.university)
        self.assertEqual(count, 1)
        teacher = Teacher.objects.get(user__username=m(1, "ENS"))
        self.assertEqual(teacher.department, self.department)

    def test_teacher_with_faculty_segment_rejected(self):
        """Le segment enseignant est défini séparément du segment faculté."""
        upload = csv_upload(f"{m(1, 'SCI')},Doe,John,t@univ.cm,Sciences,Informatique")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="teachers", university=self.university)

    def test_strict_placement_false_allows_empty_placement(self):
        upload = csv_upload(f"{m(1)},Doe,John,john@univ.cm,,")
        count = import_users(
            upload, entity="students", strict_placement=False, university=self.university
        )
        self.assertEqual(count, 1)
        student = Student.objects.get(registration_number=m(1))
        self.assertFalse(student.is_onboarded)

    def test_strict_placement_true_rejects_empty_placement(self):
        upload = csv_upload(f"{m(1)},Doe,John,john@univ.cm,,")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", strict_placement=True, university=self.university)

    def test_unsupported_extension_rejected(self):
        upload = SimpleUploadedFile("data.txt", b"whatever", content_type="text/plain")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)


class ImporterPreviewCommitTests(TestCase):
    """Aperçu signé puis confirmation : aucune écriture avant confirmation."""

    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(
            university=self.university, name="Sciences", code="SCI"
        )
        Department.objects.create(faculty=self.faculty, name="Informatique")

    def _preview(self, *rows):
        from core_scolarite.services.data_importer import preview_import

        return preview_import(
            csv_upload(*rows), entity="students", university=self.university
        )

    def test_preview_writes_nothing_and_returns_report(self):
        report = self._preview(f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique")
        self.assertEqual(report["valid"], 1)
        self.assertEqual(Student.objects.count(), 0)
        self.assertTrue(report["token"])

    def test_preview_reports_errors_line_by_line(self):
        report = self._preview("M1,Doe,John,john@univ.cm,Sciences,Informatique")
        self.assertEqual(report["valid"], 0)
        self.assertEqual(report["errors"][0]["line"], 2)
        self.assertIn("MATRICULE", report["errors"][0]["message"])

    def test_commit_creates_after_confirmation(self):
        from core_scolarite.services.data_importer import commit_import

        report = self._preview(f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique")
        result = commit_import(report["token"], university=self.university)
        self.assertEqual(result["imported"], 1)
        self.assertTrue(Student.objects.filter(registration_number=m(1)).exists())

    def test_commit_is_one_time(self):
        from core_scolarite.services.data_importer import commit_import

        report = self._preview(f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique")
        commit_import(report["token"], university=self.university)
        with self.assertRaises(ImportValidationError):
            # Le même fichier ne peut pas être confirmé deux fois (doublon).
            commit_import(report["token"], university=self.university)

    def test_commit_refuses_when_errors_without_opt_in(self):
        from core_scolarite.services.data_importer import commit_import

        report = self._preview(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            "M2,Bad,Format,nope,Sciences,Informatique",
        )
        with self.assertRaises(ImportValidationError):
            commit_import(report["token"], university=self.university)
        self.assertEqual(Student.objects.count(), 0)

    def test_commit_with_skip_invalid_keeps_valid_rows_only(self):
        from core_scolarite.services.data_importer import commit_import

        report = self._preview(
            f"{m(1)},Doe,John,john@univ.cm,Sciences,Informatique",
            "M2,Bad,Format,nope,Sciences,Informatique",
        )
        result = commit_import(
            report["token"], university=self.university, skip_invalid=True
        )
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertTrue(Student.objects.filter(registration_number=m(1)).exists())
        self.assertFalse(User.objects.filter(username="M2").exists())
