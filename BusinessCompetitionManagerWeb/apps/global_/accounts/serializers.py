"""账号相关序列化器（注册 / JWT / 个人信息）。"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.global_.memberships.models import CompetitionMembership

User = get_user_model()


class MembershipSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='competition.id')
    competitionName = serializers.CharField(source='competition.name')
    competitionStatus = serializers.CharField(source='competition.status')
    identity = serializers.CharField()
    identityLabel = serializers.CharField(source='get_identity_display')
    managedCompanies = serializers.JSONField(source='managed_companies')


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(allow_null=True, default=None)
    displayName = serializers.CharField(source='display_name', default='')
    avatar = serializers.CharField(default='')
    school = serializers.IntegerField(source='school_id', allow_null=True, default=None)
    schoolName = serializers.CharField(source='school.name', allow_null=True, default=None)
    isActive = serializers.BooleanField(source='is_active')
    isSuperuser = serializers.BooleanField(source='is_superuser')
    dateJoined = serializers.DateTimeField(source='date_joined')
    memberships = serializers.SerializerMethodField()

    def get_memberships(self, obj):
        qs = (
            CompetitionMembership.objects
            .filter(user=obj, is_active=True)
            .select_related('competition')
            .order_by('-created_at')
        )
        return MembershipSerializer(qs, many=True).data


class RegisterSerializer(serializers.ModelSerializer):
    """注册：真实姓名（``display_name``）**必填**——全站展示（顶栏/队伍成员/
    站内信通讯录/结算候选人）用的就是这个字段，缺名会让通知与名单无法辨认。"""

    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    email = serializers.EmailField(required=True)
    displayName = serializers.CharField(
        source='display_name', required=True, allow_blank=False, max_length=100,
        error_messages={
            'required': '请输入真实姓名',
            'blank': '请输入真实姓名',
            'max_length': '真实姓名最长 100 个字符',
        },
    )
    schoolId = serializers.IntegerField(source='school_id', required=False, allow_null=True, default=None)

    class Meta:
        model = User
        fields = ['username', 'password', 'email', 'displayName', 'schoolId']

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('该邮箱已被注册')
        return value

    def validate_schoolId(self, value):
        from apps.global_.schools.models import School
        if value is not None and not School.objects.filter(pk=value).exists():
            raise serializers.ValidationError('学校不存在')
        return value

    def create(self, validated_data):
        school_id = validated_data.pop('school_id', None)
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.school_id = school_id
        user.set_password(password)
        user.save()
        return user


class GipfelTokenObtainPairSerializer(TokenObtainPairSerializer):
    """签发 JWT 并携带 tokenVersion / 用户名（§14.1 用户（系统级））。"""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['tv'] = user.token_version
        token['username'] = user.username
        token['is_superuser'] = user.is_superuser
        return token
