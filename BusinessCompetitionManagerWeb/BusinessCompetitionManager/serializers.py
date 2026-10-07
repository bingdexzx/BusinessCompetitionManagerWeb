from rest_framework import serializers
from .models import Competition


class CompetitionSerializer(serializers.ModelSerializer):
    """竞赛信息序列化器"""

    class Meta:
        model = Competition
        fields = '__all__'
