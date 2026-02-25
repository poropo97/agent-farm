"""
deploy/aws_plesk.py

Automated deployment to AWS/Plesk server via SSH.
Used by code_agent after generating project files.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PleSkDeployer:
    """
    Deploys static/Python web projects to a remote server via SSH/SFTP.
    Configured via environment variables or explicit params.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 22,
        username: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        password: Optional[str] = None,
        remote_base_dir: str = "/var/www/vhosts",
    ):
        self.host     = host     or os.environ.get("DEPLOY_HOST", "")
        self.port     = port
        self.username = username or os.environ.get("DEPLOY_USER", "root")
        self.ssh_key  = ssh_key_path or os.environ.get("DEPLOY_SSH_KEY", "~/.ssh/id_rsa")
        self.password = password or os.environ.get("DEPLOY_PASSWORD", "")
        self.remote_base = remote_base_dir

    def _connect(self):
        """Return a connected paramiko SSH client."""
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key_path = os.path.expanduser(self.ssh_key)
        if os.path.exists(key_path):
            client.connect(
                self.host, port=self.port,
                username=self.username,
                key_filename=key_path,
                timeout=30,
            )
        elif self.password:
            client.connect(
                self.host, port=self.port,
                username=self.username,
                password=self.password,
                timeout=30,
            )
        else:
            raise ValueError("No SSH key or password configured for deployment")
        return client

    def deploy_static_site(self, local_dir: str, domain: str) -> dict:
        """
        Upload a static site to Plesk domain directory.

        Args:
            local_dir: Local path to site files
            domain: Domain name (used as directory name)

        Returns: {success, url, message}
        """
        if not self.host:
            return {"success": False, "message": "DEPLOY_HOST not configured"}

        try:
            import paramiko
            client = self._connect()
            sftp = client.open_sftp()

            remote_dir = f"{self.remote_base}/{domain}/httpdocs"

            # Ensure remote dir exists
            _, stdout, _ = client.exec_command(f"mkdir -p {remote_dir}")
            stdout.channel.recv_exit_status()

            # Upload files
            local_path = Path(local_dir)
            uploaded = 0
            for file in local_path.rglob("*"):
                if file.is_file():
                    rel = file.relative_to(local_path)
                    remote_file = f"{remote_dir}/{rel}"
                    remote_parent = str(Path(remote_file).parent)

                    client.exec_command(f"mkdir -p {remote_parent}")
                    sftp.put(str(file), remote_file)
                    uploaded += 1

            sftp.close()
            client.close()

            logger.info(f"Deployed {uploaded} files to {domain}")
            return {
                "success": True,
                "url": f"https://{domain}",
                "message": f"Deployed {uploaded} files",
            }

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            return {"success": False, "message": str(e)}

    def run_remote_command(self, command: str) -> dict:
        """Run a shell command on the remote server."""
        if not self.host:
            return {"success": False, "output": "DEPLOY_HOST not configured"}
        try:
            client = self._connect()
            _, stdout, stderr = client.exec_command(command, timeout=60)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()
            client.close()
            return {
                "success": exit_code == 0,
                "output": output,
                "error": error,
                "exit_code": exit_code,
            }
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}

    def deploy_python_app(self, local_dir: str, domain: str,
                          startup_command: str = "gunicorn main:app") -> dict:
        """
        Deploy a Python web app (FastAPI/Flask) using Plesk Python support.
        """
        if not self.host:
            return {"success": False, "message": "DEPLOY_HOST not configured"}

        try:
            client = self._connect()
            sftp = client.open_sftp()

            remote_dir = f"{self.remote_base}/{domain}/app"

            # Create app directory
            client.exec_command(f"mkdir -p {remote_dir}")

            # Upload all Python files
            local_path = Path(local_dir)
            for file in local_path.rglob("*"):
                if file.is_file() and not any(
                    p in str(file) for p in [".git", "__pycache__", ".env", "venv"]
                ):
                    rel = file.relative_to(local_path)
                    remote_file = f"{remote_dir}/{rel}"
                    client.exec_command(f"mkdir -p {str(Path(remote_file).parent)}")
                    sftp.put(str(file), remote_file)

            # Install deps if requirements.txt exists
            req_file = f"{remote_dir}/requirements.txt"
            try:
                sftp.stat(req_file)
                client.exec_command(
                    f"cd {remote_dir} && python3 -m pip install -r requirements.txt -q"
                )
            except FileNotFoundError:
                pass

            sftp.close()
            client.close()

            return {
                "success": True,
                "url": f"https://{domain}",
                "message": f"Deployed Python app to {domain}",
            }

        except Exception as e:
            logger.error(f"Python app deployment failed: {e}")
            return {"success": False, "message": str(e)}
