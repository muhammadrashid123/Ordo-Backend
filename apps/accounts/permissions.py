from rest_framework.permissions import SAFE_METHODS, BasePermission

from . import models as m


class CompanyOfficePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return request.method in SAFE_METHODS or request.user.role == m.User.Role.ADMIN

    def has_object_permission(self, request, view, obj):
        obj: m.Company = obj.company if view.basename == "offices" else obj
        if obj.creator == request.user:
            return True
        return m.CompanyMember.objects.filter(company=obj, user=request.user).exists()
    
class IsSuperUser(BasePermission):
    """
    Allows access only to superusers.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_superuser)
