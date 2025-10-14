import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass
class ServerMetrics:
    request_count: int = 0
    error_count: int = 0
    start_time: float = 0

    @property
    def success_rate(self) -> float:
        if self.request_count == 0:
            return 100.0
        return ((self.request_count - self.error_count) / self.request_count) * 100


class ServerConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="Server name")
    host: str = Field(default="127.0.0.1", description="Host address")
    port: int = Field(default=8000, ge=1024, le=65535, description="Port number")
    debug: bool = Field(default=False, description="Debug mode")
    shutdown_timeout: float = Field(
        default=30.0, description="Shutdown timeout seconds"
    )


class BaseMCPServer(ABC):
    def __init__(self, config: ServerConfig):
        self.config = config
        self.server_id = str(uuid.uuid4())
        self.metrics = ServerMetrics()
        self._shutdown_event = asyncio.Event()
        self._is_running = False
        self.logger = self._setup_logger()
        self.mcp: Optional[FastMCP] = None

    def _setup_logger(self) -> logging.Logger:
        server_logger = logging.getLogger(f"{self.config.name}-{self.server_id}")

        if not server_logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s - server_id=%(server_id)s",
                defaults={"server_id": self.server_id},
            )

            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            server_logger.addHandler(handler)
            server_logger.setLevel(logging.DEBUG if self.config.debug else logging.INFO)

        return server_logger

    async def _initialize_mcp(self) -> FastMCP:
        mcp = FastMCP(
            name=self.config.name,
            stateless_http=True,
            host=self.config.host,
            port=self.config.port,
            debug=self.config.debug,
        )
        return mcp

    def _get_metrics_data(self) -> dict:
        return {
            "server_id": self.server_id,
            "metrics": {
                "request_count": self.metrics.request_count,
                "error_count": self.metrics.error_count,
                "success_rate": round(self.metrics.success_rate, 2),
                "uptime_seconds": round(time.time() - self.metrics.start_time, 2),
            },
        }

    def _setup_metrics_endpoint(self) -> None:
        @self.mcp.custom_route("/metrics", methods=["GET"])
        async def metrics_endpoint(request):
            return self._get_metrics_data()

    @abstractmethod
    async def _register_tools(self) -> None:
        """Register tools for this agent. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def _register_resources(self) -> None:
        """Register resources for this agent. Must be implemented by subclasses."""
        pass

    async def _cleanup(self) -> None:
        """Cleanup resources. Override in subclasses for custom cleanup."""
        pass

    @asynccontextmanager
    async def _server_lifecycle(self):
        try:
            self.logger.info("Starting server initialization...")
            self.metrics.start_time = time.time()

            self.mcp = await self._initialize_mcp()
            await self._register_tools()
            await self._register_resources()

            self._setup_metrics_endpoint()

            self._is_running = True
            self.logger.info("Server initialization completed successfully")

            yield

        except Exception as e:
            self.logger.error(f"Server initialization failed: {e}")
            raise
        finally:
            self.logger.info("Starting server cleanup...")
            self._is_running = False

            try:
                await asyncio.wait_for(
                    self._cleanup(), timeout=self.config.shutdown_timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning("Cleanup timeout - forcing shutdown")

            self.logger.info("Server cleanup completed")

    async def run_async(self) -> None:
        async with self._server_lifecycle():
            self.logger.info(
                f"Starting {self.config.name} on {self.config.host}:{self.config.port}"
            )

            server_task = asyncio.create_task(self.mcp.run_streamable_http_async())

            try:
                done, pending = await asyncio.wait(
                    [server_task, asyncio.create_task(self._shutdown_event.wait())],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                await asyncio.wait(pending, timeout=5.0)

            except Exception as e:
                self.logger.error(f"Server runtime error: {e}")
                raise
            finally:
                self.logger.info("Server stopped")

    def run(self) -> None:
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.logger.info("Server interrupted by user")
        except Exception as e:
            self.logger.error(f"Server failed: {e}")
            raise

    def stop(self) -> None:
        if self._is_running:
            self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        return self._is_running
