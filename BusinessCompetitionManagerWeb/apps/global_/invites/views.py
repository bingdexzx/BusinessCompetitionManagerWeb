"""激活码 API（§12：POST .../invites 生成、POST /api/invites/redeem 加入比赛）。"""

import secrets
import string

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemOrCompetitionSuperAdmin
from apps.global_.competitions.models import Competition
from apps.global_.invites.models import InviteCode, InviteRedemption
from apps.global_.memberships.models import CompetitionMembership


def _invite_data(i: InviteCode) -> dict:
    return {
        'id': i.id,
        'competitionId': i.competition_id,
        'code': i.code,
        'identity': i.identity,
        'identityLabel': CompetitionMembership.Identity(i.identity).label
        if i.identity in CompetitionMembership.Identity.values else i.identity,
        'expiresAt': i.expires_at.isoformat() if i.expires_at else None,
        'maxUses': i.max_uses,
        'usedCount': i.used_count,
        'note': i.note,
        'createdAt': i.created_at.isoformat(),
    }


class InviteListCreateView(APIView):
    """激活码管理（生成/列表，仅系统超管 / 本比赛超管，§15.2）。"""

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        return Response([_invite_data(i) for i in competition.invite_codes.all()[:200]])

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        identity = request.data.get('identity') or CompetitionMembership.Identity.PLAYER
        if identity not in CompetitionMembership.Identity.values:
            return Response({'code': 400, 'message': '非法身份类型', 'details': ''}, status=400)
        alphabet = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(alphabet) for _ in range(10))
        days = int(request.data.get('validDays') or 30)
        invite = InviteCode.objects.create(
            competition=competition,
            code=code,
            identity=identity,
            expires_at=timezone.now() + timezone.timedelta(days=days),
            max_uses=int(request.data.get('maxUses') or 1),
            note=request.data.get('note') or '',
            created_by=request.user.id,
        )
        return Response(_invite_data(invite), status=status.HTTP_201_CREATED)


class InviteRedeemView(APIView):
    """凭激活码加入比赛并获得比赛内身份（§2.2 阶段四）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = (request.data.get('code') or '').strip()
        invite = InviteCode.objects.select_related('competition').filter(code=code).first()
        if invite is None or not invite.is_valid:
            return Response({'code': 400, 'message': '激活码无效或已过期', 'details': ''}, status=400)
        if InviteRedemption.objects.filter(invite=invite, user=request.user).exists():
            return Response({'code': 400, 'message': '你已使用过该激活码', 'details': ''}, status=400)

        membership, created = CompetitionMembership.objects.get_or_create(
            user=request.user, competition=invite.competition,
            defaults={'identity': invite.identity, 'is_active': True},
        )
        if not created and membership.identity != invite.identity:
            # 同一账号多比赛身份唯一（每比赛一条），激活码授予的身份优先
            membership.identity = invite.identity
            membership.is_active = True
            membership.save(update_fields=['identity', 'is_active'])

        InviteRedemption.objects.create(invite=invite, user=request.user)
        invite.used_count += 1
        invite.save(update_fields=['used_count'])
        return Response({
            'competitionId': invite.competition_id,
            'competitionName': invite.competition.name,
            'identity': membership.identity,
            'identityLabel': membership.get_identity_display(),
        }, status=status.HTTP_201_CREATED)
