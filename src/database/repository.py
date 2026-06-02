"""
数据仓库 - 使用Repository模式
"""
from typing import List, Optional, Type, TypeVar, Generic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime
import structlog

logger = structlog.get_logger()

T = TypeVar('T')

class BaseRepository(Generic[T]):
    """基础仓库"""
    
    def __init__(self, session: AsyncSession, model: Type[T]):
        self.session = session
        self.model = model
    
    async def create(self, **kwargs) -> T:
        """创建记录"""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance
    
    async def get_by_id(self, id: int) -> Optional[T]:
        """根据ID获取"""
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        """获取所有记录"""
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    async def update(self, id: int, **kwargs) -> Optional[T]:
        """更新记录"""
        kwargs['updated_at'] = datetime.now()
        await self.session.execute(
            update(self.model)
            .where(self.model.id == id)
            .values(**kwargs)
        )
        await self.session.commit()
        return await self.get_by_id(id)
    
    async def delete(self, id: int) -> bool:
        """删除记录"""
        await self.session.execute(
            delete(self.model).where(self.model.id == id)
        )
        await self.session.commit()
        return True

class ProjectRepository(BaseRepository):
    """项目仓库"""
    
    def __init__(self, session: AsyncSession):
        from src.database.models import VerificationProject
        super().__init__(session, VerificationProject)
    
    async def get_active_projects(self) -> List:
        """获取活跃项目"""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.status == "active")
            .order_by(self.model.created_at.desc())
        )
        return result.scalars().all()
    
    async def get_with_tasks(self, project_id: int):
        """获取项目及关联任务"""
        result = await self.session.execute(
            select(self.model)
            .options(selectinload(self.model.tasks))
            .where(self.model.id == project_id)
        )
        return result.scalar_one_or_none()

class TaskRepository(BaseRepository):
    """任务仓库"""
    
    def __init__(self, session: AsyncSession):
        from src.database.models import VerificationTask
        super().__init__(session, VerificationTask)
    
    async def get_tasks_by_project(self, project_id: int) -> List:
        """获取项目的所有任务"""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.created_at)
        )
        return result.scalars().all()
    
    async def get_tasks_by_status(self, status: str) -> List:
        """根据状态获取任务"""
        result = await self.session.execute(
            select(self.model)
            .where(self.model.status == status)
        )
        return result.scalars().all()