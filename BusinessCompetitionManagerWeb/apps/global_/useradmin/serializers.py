"""用户管理序列化器（对外契约字段全部 camelCase）。

只做**输出**序列化：账号列表项 / 详情（含 memberships 概要）；
输入校验在 views 内按既有风格直接返回中文错误（见 apps.global_.accounts.views）。
"""

from rest_framework import serializers

from apps.global_.memberships.models import CompetitionMembership


class MembershipSummarySerializer(serializers.Serializer):
    """memberships 概要：competitionId / identity / managedCompanies。"""

    competitionId = serializers.IntegerField(source='competition_id')
    identity = serializers.CharField()
    managedCompanies = serializers.JSONField(source='managed_companies')


class UserSerializer(serializers.Serializer):
    """账号列表项 / 详情。

    形状：id/username/displayName/email/school{id,name}/isSuperuser/isActive/
    createdAt/memberships[]。
    """

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    displayName = serializers.CharField(source='display_name', default='')
    email = serializers.EmailField(allow_null=True, default=None)
    school = serializers.SerializerMethodField()
    isSuperuser = serializers.BooleanField(source='is_superuser')
    isActive = serializers.BooleanField(source='is_active')
    createdAt = serializers.DateTimeField(source='date_joined')
    memberships = serializers.SerializerMethodField()

    def get_school(self, obj):
        if not obj.school_id:
            return None
        return {'id': obj.school_id, 'name': obj.school.name}

    def get_memberships(self, obj):
        # 列表批量序列化时由视图预取（context['memberships_by_user']），避免 N+1
        cache = self.context.get('memberships_by_user')
        if cache is not None:
            rows = cache.get(obj.pk, [])
        else:
            rows = list(membership_summary_qs(obj))
        return MembershipSummarySerializer(rows, many=True).data


def membership_summary_qs(user):
    """该账号的 memberships 概要集合（与账号信息一致：仅有效身份，最近在前）。"""
    return (
        CompetitionMembership.objects
        .filter(user=user, is_active=True)
        .order_by('-created_at', '-id')
    )


def memberships_by_user(users):
    """批量预取 {user_id: [membership, ...]}，供列表序列化使用。"""
    user_ids = [u.pk for u in users]
    grouped = {uid: [] for uid in user_ids}
    rows = (
        CompetitionMembership.objects
        .filter(user_id__in=user_ids, is_active=True)
        .order_by('-created_at', '-id')
    )
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row)
    return grouped
