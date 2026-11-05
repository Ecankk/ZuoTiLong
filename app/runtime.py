"""Own one application's services, Agent and temporary upload inbox."""

from contextlib import contextmanager

from app.agent.controller import AgentController
from app.config import AppConfig
from app.documents.progress import interrupt_old_progress
from app.services.knowledge import KnowledgeService
from app.services.knowledge_catalog import KnowledgeCatalogService
from app.services.knowledge_links import KnowledgeLinksService
from app.services.library import LibraryService
from app.services.local_state import LocalStateService
from app.services.mobile import MobileInbox
from app.services.papers import PaperService
from app.services.practice import PracticeService
from app.services.question_index import QuestionIndexService
from app.services.resources import ResourceService
from app.services.workspace import WorkspaceService
from app.services.frontend_reads import FrontendReads
from app.services.task_summary import TaskSummary
from app.services.events import EventStream
from app.storage.database import Database


class AppRuntime:
    def __init__(self, config: AppConfig, *, bridge=None, agent_factory=None, manage_agent=True):
        self.config = config
        self.database = Database(config)
        self.bridge = bridge
        self.agent_factory = agent_factory
        self.manage_agent = manage_agent
        self.mobile = None

        self.papers = PaperService(config, self.database)
        self.practice = PracticeService(config, self.database)
        from app.learning.free_practice import FreePracticeService
        self.free_practice=FreePracticeService(config,self.database)
        self.workspace = WorkspaceService(config, self.database)
        self.resources = ResourceService(config, self.database)
        self.library = LibraryService(config, self.database)
        self.local = LocalStateService(config, self.database)
        self.knowledge = KnowledgeService(config, self.database)
        self.knowledge_links = KnowledgeLinksService(config, self.database)
        self.knowledge_catalog = KnowledgeCatalogService(config, self.database)
        self.question_index = QuestionIndexService(config, self.database)
        self.agent = AgentController(self)
        self.frontend = FrontendReads(self)
        self.tasks = TaskSummary(self)
        self.events = EventStream(self)

    def start(self) -> None:
        self.database.initialize()
        self.knowledge_links.prepare_index()
        interrupt_old_progress(self.config.data)
        if self.bridge is None and self.agent_factory:
            self.bridge = self.agent_factory(self.config.root, self.config.data)
            self.bridge.learning_db = self.config.database
            if hasattr(self.bridge,'context'):self.bridge.context.learning_db = self.config.database
            from app.agent.bridge import CodexBridge
            if isinstance(self.bridge,CodexBridge):
                self.bridge.auto_connect = True
                self.bridge.workflow_wakeup.set()
        self.events.start()

    def close(self) -> None:
        self.events.close()
        self.frontend.close()
        self.workspace.close()
        if self.mobile:
            self.mobile.stop()
        if self.bridge and self.manage_agent:
            self.bridge.close()
            if self.agent_factory:
                self.bridge = None

    @contextmanager
    def write_guard(self):
        if self.bridge:
            with self.bridge.lock:
                self.bridge.assert_user_write_allowed()
                yield
        else:
            yield

    def mutate(self, fn, *args, **kwargs):
        with self.write_guard():
            result = fn(*args, **kwargs)
        self.wake()
        return result

    def wake(self) -> None:
        if self.bridge:
            self.bridge.workflow_wakeup.set()

    def mobile_start(self, body):
        if body.get('confirmed') is not True:
            raise ValueError('请确认仅在可信局域网临时接收照片')
        if self.mobile is None:
            self.mobile = MobileInbox(self.database.connect, self.config.data, self.write_guard)
        return self.mobile.start(body.get('target'))

    def mobile_stop(self):
        return self.mobile.stop() if self.mobile else {'active': False}

    def mobile_state(self):
        return self.mobile.state() if self.mobile else {'active': False, 'images': []}
