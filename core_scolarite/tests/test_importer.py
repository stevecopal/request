"""Tests du service d'import ETL (data_importer)."""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import Department, Faculty, Student
from accounts.tests.factories import make_university
from core_scolarite.services.data_importer import ImportValidationError, import_users

HEADER = "MATRICULE,NOM,PRENOM,EMAIL,FACULTE,DEPARTEMENT"


def csv_upload(*rows, header=HEADER):
    content = "\n".join([header, *rows])
    return SimpleUploadedFile("etudiants.csv", content.encode("utf-8"), content_type="text/csv")


class ImporterValidationTests(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.department = Department.objects.create(
            faculty=self.faculty, name="Informatique"
        )

    def test_missing_header_raises(self):
        upload = csv_upload("M1,Doe,John,a@b.c,Sciences,Informatique", header="MATRICULE,NOM,PRENOM")
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertIn("EMAIL", ctx.exception.message)

    def test_successful_import_creates_students(self):
        upload = csv_upload(
            "M1,Doe,John,john@univ.cm,Sciences,Informatique",
            "M2,Roe,Jane,jane@univ.cm,Sciences,Informatique",
        )
        count = import_users(upload, entity="students", university=self.university)
        self.assertEqual(count, 2)
        student = Student.objects.get(registration_number="M1")
        self.assertTrue(student.is_onboarded)
        self.assertTrue(User.objects.filter(username="M1").exists())

    def test_unknown_faculty_reports_line_number(self):
        upload = csv_upload(
            "M1,Doe,John,john@univ.cm,Sciences,Informatique",
            "M2,Roe,Jane,jane@univ.cm,INEXISTANTE,Informatique",
        )
        with self.assertRaises(ImportValidationError) as ctx:
            import_users(upload, entity="students", university=self.university)
        self.assertEqual(ctx.exception.errors[0]["line"], 3)

    def test_department_not_in_faculty_rejected(self):
        upload = csv_upload("M1,Doe,John,john@univ.cm,Sciences,Histoire")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)

    def test_rollback_is_total(self):
        """Un fichier valide + une ligne cassée ⇒ 0 enregistrement."""
        upload = csv_upload(
            "M1,Doe,John,john@univ.cm,Sciences,Informatique",
            "M2,Roe,Jane,jane@univ.cm,Sciences,Informatique",
            "M3,Bad,Row,row@univ.cm,Sciences,Inexistant",
        )
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(User.objects.filter(username__in=["M1", "M2"]).count(), 0)

    def test_duplicate_matricule_in_file_rejected(self):
        upload = csv_upload(
            "M1,Doe,John,john@univ.cm,Sciences,Informatique",
            "M1,Roe,Jane,jane@univ.cm,Sciences,Informatique",
        )
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)

    def test_strict_placement_false_allows_empty_placement(self):
        upload = csv_upload("M1,Doe,John,john@univ.cm,,")
        count = import_users(upload, entity="students", strict_placement=False, university=self.university)
        self.assertEqual(count, 1)
        student = Student.objects.get(registration_number="M1")
        self.assertFalse(student.is_onboarded)

    def test_strict_placement_true_rejects_empty_placement(self):
        upload = csv_upload("M1,Doe,John,john@univ.cm,,")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", strict_placement=True, university=self.university)

    def test_unsupported_extension_rejected(self):
        upload = SimpleUploadedFile("data.txt", b"whatever", content_type="text/plain")
        with self.assertRaises(ImportValidationError):
            import_users(upload, entity="students", university=self.university)
