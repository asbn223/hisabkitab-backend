# apps/tenants/views.py
"""
API views for tenant management.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction

from .models import Tenant, TenantUser, TenantSettings
from .serializers import (
    TenantListSerializer, TenantDetailSerializer, TenantCreateSerializer,
    TenantUserSerializer, TenantSettingsSerializer
)
from .permissions import TenantPermission, IsTenantAdmin, IsTenantOwner


class TenantViewSet(viewsets.ModelViewSet):
    """
    ViewSet for tenant management.
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        """Return tenants where user is member."""
        user_id = self.request.user.id

        # Superuser sees all
        if self.request.user.is_superuser:
            return Tenant.objects.all()

        tenant_ids = TenantUser.objects.filter(
            user_id=user_id,
            is_active=True
        ).values_list('tenant_id', flat=True)

        return Tenant.objects.filter(id__in=tenant_ids)

    def get_serializer_class(self):
        if self.action == 'create':
            return TenantCreateSerializer
        if self.action in ['update', 'partial_update']:
            return TenantDetailSerializer
        if self.action == 'retrieve':
            return TenantDetailSerializer
        return TenantListSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        """Create tenant and add creator as owner."""
        tenant = serializer.save()

        # Add creator as owner
        TenantUser.objects.create(
            tenant=tenant,
            user_id=self.request.user.id,
            role='owner',
            name=getattr(self.request.user, 'name', ''),
            email=getattr(self.request.user, 'email', ''),
        )

        # Create default settings
        TenantSettings.objects.create(tenant=tenant)

        # Seed chart of accounts
        from apps.accounts.services import seed_chart_of_accounts
        seed_chart_of_accounts(tenant)

        return tenant

    @action(detail=True, methods=['post'], permission_classes=[IsTenantAdmin])
    def invite_user(self, request, pk=None):
        """Invite user to tenant."""
        tenant = self.get_object()

        serializer = TenantUserSerializer(data={
            'tenant': tenant.id,
            'user_id': request.data.get('user_id'),
            'role': request.data.get('role', 'viewer'),
            'name': request.data.get('name', ''),
            'email': request.data.get('email', ''),
        })
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # TODO: Send invitation email

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def users(self, request, pk=None):
        """List all users in tenant."""
        tenant = self.get_object()
        users = TenantUser.objects.filter(tenant=tenant)
        serializer = TenantUserSerializer(users, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'patch'])
    def tenant_settings(self, request, pk=None):
        """Get or update tenant settings."""
        tenant = self.get_object()
        settings_obj, _ = TenantSettings.objects.get_or_create(tenant=tenant)

        if request.method == 'GET':
            serializer = TenantSettingsSerializer(settings_obj)
            return Response(serializer.data)

        # PATCH
        serializer = TenantSettingsSerializer(
            settings_obj,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsTenantOwner])
    def deactivate(self, request, pk=None):
        """Deactivate tenant (soft delete)."""
        tenant = self.get_object()
        tenant.is_active = False
        tenant.save()
        return Response({'status': 'deactivated'})

    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get current tenant from request context."""
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response(
                {'error': 'No tenant in request context'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = TenantDetailSerializer(tenant)
        return Response(serializer.data)


class TenantUserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing tenant users.
    """
    serializer_class = TenantUserSerializer
    permission_classes = [IsAuthenticated, TenantPermission, IsTenantAdmin]

    def get_queryset(self):
        """Filter by current tenant."""
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return TenantUser.objects.none()
        return TenantUser.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        """Set tenant from request."""
        tenant = self.request.tenant
        serializer.save(tenant=tenant)

    @action(detail=True, methods=['post'])
    def change_role(self, request, pk=None):
        """Change user role."""
        user = self.get_object()
        new_role = request.data.get('role')

        if new_role not in [r[0] for r in TenantUser.ROLE_CHOICES]:
            return Response(
                {'error': 'Invalid role'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prevent changing own role if owner
        if user.user_id == request.user.id and user.role == 'owner':
            return Response(
                {'error': 'Cannot change own owner role'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.role = new_role
        user.save()

        return Response(TenantUserSerializer(user).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate user."""
        user = self.get_object()

        # Prevent deactivating self
        if user.user_id == request.user.id:
            return Response(
                {'error': 'Cannot deactivate yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prevent deactivating last owner
        if user.role == 'owner':
            owner_count = TenantUser.objects.filter(
                tenant=user.tenant,
                role='owner',
                is_active=True
            ).count()
            if owner_count <= 1:
                return Response(
                    {'error': 'Cannot deactivate last owner'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        user.is_active = False
        user.save()

        return Response({'status': 'deactivated'})