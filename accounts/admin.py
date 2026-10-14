"""Administration Django — accounts (identités, rôles, profils)."""

from django.contrib import admin

from .models import Department, Faculty, Student, Teacher


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty")
    list_filter = ("faculty",)
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
