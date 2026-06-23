"""
API 依赖注入
================================================
提供认证依赖,从 Authorization header 提取 JWT token 并验证
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth.jwt_handler import verify_access_token
from auth.models import User, get_user_by_id


# Bearer Token 安全方案
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    FastAPI 依赖:验证 JWT token 并返回当前用户

    用法:
        @router.post("/example")
        def example(user: User = Depends(get_current_user)):
            ...

    :param credentials: Bearer token 凭证
    :return: 当前登录的 User 对象
    :raises HTTPException: 401 token 无效/过期/用户不存在
    """
    token = credentials.credentials
    payload = verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )
    return user


def require_roles(*roles: str):
    """
    FastAPI 依赖工厂:要求用户具有指定角色之一

    用法:
        @router.post("/upload")
        def upload(user: User = Depends(require_roles("admin", "editor"))):
            ...

    :param roles: 允许的角色列表
    :return: 依赖函数
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足,需要角色: {', '.join(roles)}",
            )
        return user
    return role_checker
