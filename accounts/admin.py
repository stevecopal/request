"""Administration Django — accounts (identités, rôles, profils)."""

from django.contrib import admin

from .models import (
    AcademicYear,
    Department,
    Faculty,
    Program,
    PushSubscription,
    Student,
    Teacher,
    University,
)


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "is_active")
    list_filter = ("university", "is_active")
    search_fields = ("name", "university__name")
    autocomplete_fields = ("university",)
    ordering = ("university", "name")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty", "is_active")
    list_filter = ("faculty", "is_active")
    search_fields = ("name", "faculty__name")
    autocomplete_fields = ("faculty",)
    ordering = ("faculty", "name")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("registration_number", "full_name", "department", "is_onboarded")
    list_filter = ("faculty", "department")
    search_fields = ("registration_number", "user__username", "user__last_name", "user__first_name")
    autocomplete_fields = ("user", "faculty", "department")
    ordering = ("registration_number",)
    readonly_fields = ("id",)

    @admin.display(boolean=True, description="Profil complété")
    def is_onboarded(self, obj):
        return obj.is_onboarded


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("full_name", "title", "department", "faculty")
    list_filter = ("title", "faculty", "department")
    search_fields = ("user__username", "user__last_name", "user__first_name")
    autocomplete_fields = ("user", "faculty", "department")
    ordering = ("user__last_name", "user__first_name")
    readonly_fields = ("id",)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "endpoint", "created_at")
    search_fields = ("user__username", "endpoint")
    readonly_fields = ("id", "endpoint", "p256dh", "auth", "created_at", "updated_at")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "level", "department", "is_active")
    list_filter = ("level", "is_active", "department__faculty")
    search_fields = ("code", "name", "department__name")
    ordering = ("department__faculty__name", "department__name", "code")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("code", "start_date", "end_date", "is_current")
    list_filter = ("is_current",)
    search_fields = ("code",)
    ordering = ("-code",)
