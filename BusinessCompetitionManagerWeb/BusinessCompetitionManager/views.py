from rest_framework import viewsets
from .models import Competition
from .serializers import CompetitionSerializer

# 在此处创建你的视图。


class CompetitionViewSet(viewsets.ModelViewSet):
    """竞赛信息视图集，提供增删改查接口"""

    queryset = Competition.objects.all()
    serializer_class = CompetitionSerializer
