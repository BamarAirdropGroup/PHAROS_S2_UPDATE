import json
import os
import re
import time
import random
import asyncio
import pytz
from datetime import datetime
from base64 import b64encode
from colorama import Fore, Style, init
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from web3 import Web3
from web3.exceptions import TransactionNotFound, InvalidAddress, ContractLogicError
from eth_account import Account
from aiohttp import ClientSession, ClientTimeout, ClientResponseError, BasicAuth
from aiohttp_socks import ProxyConnector

# Initialize colorama for colored console output
init(autoreset=True)

# Timezone for logging
wib = pytz.timezone('Asia/Singapore')

# Hardcoded public key for authentication (consider moving to env variable for security)
PUBLIC_KEY_PEM = b"""
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDWPv2qP8+xLABhn3F/U/hp76HP
e8dD7kvPUh70TC14kfvwlLpCTHhYf2/6qulU1aLWpzCz3PJr69qonyqocx8QlThq
5Hik6H/5fmzHsjFvoPeGN5QRwYsVUH07MbP7MNbJH5M2zD5Z1WEp9AHJklITbS1z
h23cf2WfZ0vwDYzZ8QIDAQAB
-----END PUBLIC KEY-----
"""

class AutoStaking:
    def __init__(self):
        self.HEADERS = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://autostaking.pro",
            "Referer": "https://autostaking.pro/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0.0.0 Safari/537.36"
            )
        }
        self.BASE_API = "https://asia-east2-auto-staking.cloudfunctions.net/auto_staking_pharos_v7"
        self.RPC_URL = "https://testnet.dplabs-internal.com/"
        self.USDC_CONTRACT_ADDRESS = "0x72df0bcd7276f2dFbAc900D1CE63c272C4BCcCED"
        self.USDT_CONTRACT_ADDRESS = "0xD4071393f8716661958F766DF660033b3d35fD29"
        self.MUSD_CONTRACT_ADDRESS = "0x7F5e05460F927Ee351005534423917976F92495e"
        self.mvMUSD_CONTRACT_ADDRESS = "0xF1CF5D79bE4682D50f7A60A047eaCa9bD351fF8e"
        self.STAKING_ROUTER_ADDRESS = "0x11cD3700B310339003641Fdce57c1f9BD21aE015"
        self.ERC20_CONTRACT_ABI = json.loads('''[
            {"type":"function","name":"balanceOf","stateMutability":"view","inputs":[{"name":"address","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},
            {"type":"function","name":"allowance","stateMutability":"view","inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},
            {"type":"function","name":"approve","stateMutability":"nonpayable","inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}]},
            {"type":"function","name":"decimals","stateMutability":"view","inputs":[],"outputs":[{"name":"","type":"uint8"}]},
            {"type":"function","name":"claimFaucet","stateMutability":"nonpayable","inputs":[],"outputs":[{"name":"","type":"uint256"}]}
        ]''')
        self.AUTOSTAKING_CONTRACT_ABI = [
            {
                "type": "function",
                "name": "getNextFaucetClaimTime",
                "stateMutability": "view",
                "inputs": [{"name": "user", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256"}]
            }
        ]
        self.PROMPT = (
            "1. Must: TVL > $1,000,000.\n"
            "2. Priority: Highest TVL for max safety.\n"
            "3. Allocation: Select top 3 products by TVL (TVL > $1,000,000), distribute total investment proportionally to TVL "
            "(e.g., X/(X+Y+Z), Y/(X+Y+Z), Z/(X+Y+Z)), where X, Y, Z are TVLs, ensuring higher TVL gets larger share."
        )
        self.proxies = []
        self.proxy_index = 0
        self.account_proxies = {}
        self.auth_tokens = {}
        self.used_nonce = {}
        self.staking_count = 0
        self.usdc_amount = 0.0
        self.usdt_amount = 0.0
        self.musd_amount = 0.0
        self.min_delay = 0
        self.max_delay = 0

    def clear_terminal(self):
        """Clear the terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def log(self, message):
        """Log a message with timestamp and color formatting."""
        print(
            f"{Fore.CYAN + Style.BRIGHT}[ {datetime.now().astimezone(wib).strftime('%x %X %Z')} ]{Style.RESET_ALL}"
            f"{Fore.WHITE + Style.BRIGHT} | {Style.RESET_ALL}{message}",
            flush=True
        )

    def welcome(self):
        """Display the welcome message for the bot."""
        print(
            f"\n{Fore.GREEN + Style.BRIGHT}AutoStaking{Fore.BLUE + Style.BRIGHT} Auto BOT\n"
            f"{Fore.YELLOW + Style.BRIGHT}====================================\n"
        )

    def format_seconds(self, seconds):
        """Format seconds into HH:MM:SS."""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

    async def load_proxies(self, use_proxy_choice: int):
        """Load proxies from file or Proxyscrape API."""
        filename = "proxy.txt"
        try:
            if use_proxy_choice == 1:
                async with ClientSession(timeout=ClientTimeout(total=30)) as session:
                    async with session.get("https://raw.githubusercontent.com/monosans/proxy-list/refs/heads/main/proxies/http.txt") as response:
                        response.raise_for_status()
                        content = await response.text()
                        with open(filename, 'w') as f:
                            f.write(content)
                        self.proxies = [line.strip() for line in content.splitlines() if line.strip()]
            else:
                if not os.path.exists(filename):
                    self.log(f"{Fore.RED + Style.BRIGHT}File {filename} Not Found.{Style.RESET_ALL}")
                    return
                with open(filename, 'r') as f:
                    self.proxies = [line.strip() for line in f.read().splitlines() if line.strip()]

            if not self.proxies:
                self.log(f"{Fore.RED + Style.BRIGHT}No Proxies Found.{Style.RESET_ALL}")
                return

            self.log(
                f"{Fore.GREEN + Style.BRIGHT}Proxies Total: {Style.RESET_ALL}"
                f"{Fore.WHITE + Style.BRIGHT}{len(self.proxies)}{Style.RESET_ALL}"
            )
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Failed to Load Proxies: {e}{Style.RESET_ALL}")
            self.proxies = []

    def check_proxy_schemes(self, proxy):
        """Ensure proxy has a valid scheme (http, https, socks4, socks5)."""
        schemes = ["http://", "https://", "socks4://", "socks5://"]
        if any(proxy.startswith(scheme) for scheme in schemes):
            return proxy
        return f"http://{proxy}"

    def get_next_proxy_for_account(self, token):
        """Get the next proxy for a given account."""
        if token not in self.account_proxies:
            if not self.proxies:
                return None
            proxy = self.check_proxy_schemes(self.proxies[self.proxy_index])
            self.account_proxies[token] = proxy
            self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        return self.account_proxies[token]

    def rotate_proxy_for_account(self, token):
        """Rotate to the next proxy for a given account."""
        if not self.proxies:
            return None
        proxy = self.check_proxy_schemes(self.proxies[self.proxy_index])
        self.account_proxies[token] = proxy
        self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        return proxy

    def build_proxy_config(self, proxy=None):
        """Build proxy configuration for HTTP or SOCKS proxies."""
        if not proxy:
            return None, None, None

        if proxy.startswith("socks"):
            connector = ProxyConnector.from_url(proxy)
            return connector, None, None
        elif proxy.startswith("http"):
            match = re.match(r"http://(.*?):(.*?)@(.*)", proxy)
            if match:
                username, password, host_port = match.groups()
                clean_url = f"http://{host_port}"
                auth = BasicAuth(username, password)
                return None, clean_url, auth
            else:
                return None, proxy, None
        raise ValueError("Unsupported Proxy Type.")

    def generate_address(self, private_key: str):
        """Generate an Ethereum address from a private key."""
        try:
            account = Account.from_key(private_key)
            return account.address
        except ValueError as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Invalid Private Key: {e}{Style.RESET_ALL}")
            return None

    def mask_account(self, account):
        """Mask an account address for logging."""
        try:
            return account[:6] + '*' * 6 + account[-6:]
        except (TypeError, AttributeError):
            return None

    def generate_auth_token(self, address: str):
        """Generate an authentication token using public key encryption."""
        try:
            public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
            ciphertext = public_key.encrypt(
                address.encode('utf-8'),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            return b64encode(ciphertext).decode('utf-8')
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Failed to Generate Auth Token: {e}{Style.RESET_ALL}")
            return None

    def generate_recommendation_payload(self, address: str):
        """Generate payload for financial portfolio recommendation API."""
        try:
            usdc_assets = int(self.usdc_amount * (10 ** 6))
            usdt_assets = int(self.usdt_amount * (10 ** 6))
            musd_assets = int(self.musd_amount * (10 ** 6))
            return {
                "user": address,
                "profile": self.PROMPT,
                "userPositions": [],
                "userAssets": [
                    {
                        "chain": {"id": 688688},
                        "name": "USDC",
                        "symbol": "USDC",
                        "decimals": 6,
                        "address": self.USDC_CONTRACT_ADDRESS,
                        "assets": str(usdc_assets),
                        "price": 1,
                        "assetsUsd": self.usdc_amount
                    },
                    {
                        "chain": {"id": 688688},
                        "name": "USDT",
                        "symbol": "USDT",
                        "decimals": 6,
                        "address": self.USDT_CONTRACT_ADDRESS,
                        "assets": str(usdt_assets),
                        "price": 1,
                        "assetsUsd": self.usdt_amount
                    },
                    {
                        "chain": {"id": 688688},
                        "name": "MockUSD",
                        "symbol": "MockUSD",
                        "decimals": 6,
                        "address": self.MUSD_CONTRACT_ADDRESS,
                        "assets": str(musd_assets),
                        "price": 1,
                        "assetsUsd": self.musd_amount
                    }
                ],
                "chainIds": [688688],
                "tokens": ["USDC", "USDT", "MockUSD"],
                "protocols": ["MockVault"],
                "env": "pharos"
            }
        except Exception as e:
            raise ValueError(f"Failed to Generate Recommendation Payload: {e}")

    def generate_transactions_payload(self, address: str, change_tx: list):
        """Generate payload for transaction generation API."""
        try:
            return {
                "user": address,
                "changes": change_tx,
                "prevTransactionResults": {}
            }
        except Exception as e:
            raise ValueError(f"Failed to Generate Transactions Payload: {e}")

    async def get_web3_with_check(self, address: str, use_proxy: bool, retries=3, timeout=60):
        """Initialize Web3 connection with retries."""
        request_kwargs = {"timeout": timeout}
        proxy = self.get_next_proxy_for_account(address) if use_proxy else None
        if use_proxy and proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        for attempt in range(retries):
            try:
                web3 = Web3(Web3.HTTPProvider(self.RPC_URL, request_kwargs=request_kwargs))
                web3.eth.get_block_number()
                return web3
            except Exception as e:
                if attempt < retries - 1:
                    self.log(f"{Fore.YELLOW}Web3 Connection Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
                    await asyncio.sleep(3)
                    continue
                raise ConnectionError(f"Failed to Connect to RPC after {retries} attempts: {e}")

    async def get_token_balance(self, address: str, contract_address: str, use_proxy: bool):
        """Get token balance for a given address and contract."""
        try:
            web3 = await self.get_web3_with_check(address, use_proxy)
            token_contract = web3.eth.contract(address=web3.to_checksum_address(contract_address), abi=self.ERC20_CONTRACT_ABI)
            balance = token_contract.functions.balanceOf(web3.to_checksum_address(address)).call()
            decimals = token_contract.functions.decimals().call()
            return balance / (10 ** decimals)
        except (InvalidAddress, ContractLogicError) as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Invalid Contract or Address: {e}{Style.RESET_ALL}")
            return None
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Failed to Get Token Balance: {e}{Style.RESET_ALL}")
            return None

    async def send_raw_transaction_with_retries(self, account, web3, tx, retries=5):
        """Send a raw transaction with retries and nonce handling."""
        for attempt in range(retries):
            try:
                tx['nonce'] = web3.eth.get_transaction_count(tx['from'], "pending")
                signed_tx = web3.eth.account.sign_transaction(tx, account)
                raw_tx = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                return web3.to_hex(raw_tx)
            except (TransactionNotFound, ValueError) as e:
                self.log(f"{Fore.YELLOW}Transaction Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
                if "nonce" in str(e).lower():
                    self.used_nonce[tx['from']] = web3.eth.get_transaction_count(tx['from'], "pending")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                self.log(f"{Fore.YELLOW}Transaction Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Transaction Failed After Maximum Retries")

    async def wait_for_receipt_with_retries(self, web3, tx_hash, retries=5):
        """Wait for transaction receipt with retries."""
        for attempt in range(retries):
            try:
                receipt = await asyncio.to_thread(web3.eth.wait_for_transaction_receipt, tx_hash, timeout=300)
                return receipt
            except TransactionNotFound:
                self.log(f"{Fore.YELLOW}Receipt Attempt {attempt + 1} Failed: Transaction Not Found{Style.RESET_ALL}")
            except Exception as e:
                self.log(f"{Fore.YELLOW}Receipt Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
            await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Transaction Receipt Not Found After Maximum Retries")

    async def get_next_faucet_claim_time(self, address: str, use_proxy: bool):
        """Get the next faucet claim time for an address."""
        try:
            web3 = await self.get_web3_with_check(address, use_proxy)
            contract_address = web3.to_checksum_address(self.mvMUSD_CONTRACT_ADDRESS)
            token_contract = web3.eth.contract(address=contract_address, abi=self.AUTOSTAKING_CONTRACT_ABI)
            return token_contract.functions.getNextFaucetClaimTime(web3.to_checksum_address(address)).call()
        except (InvalidAddress, ContractLogicError) as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Invalid Contract or Address: {e}{Style.RESET_ALL}")
            return None
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Failed to Get Faucet Claim Time: {e}{Style.RESET_ALL}")
            return None

    async def perform_claim_faucet(self, account: str, address: str, use_proxy: bool):
        """Perform a faucet claim transaction."""
        try:
            web3 = await self.get_web3_with_check(address, use_proxy)
            contract_address = web3.to_checksum_address(self.mvMUSD_CONTRACT_ADDRESS)
            token_contract = web3.eth.contract(address=contract_address, abi=self.ERC20_CONTRACT_ABI)
            claim_data = token_contract.functions.claimFaucet()
            estimated_gas = claim_data.estimate_gas({"from": address})
            max_priority_fee = web3.to_wei(1, "gwei")
            max_fee = max_priority_fee
            current_nonce = web3.eth.get_transaction_count(address, "pending")
            claim_tx = claim_data.build_transaction({
                "from": web3.to_checksum_address(address),
                "gas": int(estimated_gas * 1.2),
                "maxFeePerGas": int(max_fee),
                "maxPriorityFeePerGas": int(max_priority_fee),
                "nonce": current_nonce,
                "chainId": web3.eth.chain_id,
            })
            tx_hash = await self.send_raw_transaction_with_retries(account, web3, claim_tx)
            receipt = await self.wait_for_receipt_with_retries(web3, tx_hash)
            self.used_nonce[address] = current_nonce + 1
            return tx_hash, receipt.blockNumber
        except (InvalidAddress, ContractLogicError) as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Invalid Contract or Address: {e}{Style.RESET_ALL}")
            return None, None
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Faucet Claim Failed: {e}{Style.RESET_ALL}")
            return None, None

    async def approving_token(self, account: str, address: str, router_address: str, asset_address: str, amount: float, use_proxy: bool):
        """Approve a token for spending by the staking router."""
        try:
            web3 = await self.get_web3_with_check(address, use_proxy)
            spender = web3.to_checksum_address(router_address)
            token_contract = web3.eth.contract(address=web3.to_checksum_address(asset_address), abi=self.ERC20_CONTRACT_ABI)
            decimals = token_contract.functions.decimals().call()
            amount_to_wei = int(amount * (10 ** decimals))
            allowance = token_contract.functions.allowance(address, spender).call()
            if allowance < amount_to_wei:
                approve_data = token_contract.functions.approve(spender, 2**256 - 1)
                estimated_gas = approve_data.estimate_gas({"from": address})
                max_priority_fee = web3.to_wei(1, "gwei")
                max_fee = max_priority_fee
                current_nonce = web3.eth.get_transaction_count(address, "pending")
                approve_tx = approve_data.build_transaction({
                    "from": address,
                    "gas": int(estimated_gas * 1.2),
                    "maxFeePerGas": int(max_fee),
                    "maxPriorityFeePerGas": int(max_priority_fee),
                    "nonce": current_nonce,
                    "chainId": web3.eth.chain_id,
                })
                tx_hash = await self.send_raw_transaction_with_retries(account, web3, approve_tx)
                receipt = await self.wait_for_receipt_with_retries(web3, tx_hash)
                self.used_nonce[address] = current_nonce + 1
                explorer = f"https://testnet.pharosscan.xyz/tx/{tx_hash}"
                self.log(f"{Fore.CYAN + Style.BRIGHT}   Approve :{Style.RESET_ALL}{Fore.GREEN + Style.BRIGHT} Success {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}   Block   :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {receipt.blockNumber} {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}   Tx Hash :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {tx_hash} {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}   Explorer:{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {explorer} {Style.RESET_ALL}")
                await asyncio.sleep(5)
            return True
        except (InvalidAddress, ContractLogicError) as e:
            raise ValueError(f"Invalid Contract or Address: {e}")
        except Exception as e:
            raise ValueError(f"Approving Token Contract Failed: {e}")

    async def perform_staking(self, account: str, address: str, change_tx: list, use_proxy: bool):
        """Perform staking transactions."""
        try:
            web3 = await self.get_web3_with_check(address, use_proxy)
            await self.approving_token(account, address, self.STAKING_ROUTER_ADDRESS, self.USDC_CONTRACT_ADDRESS, self.usdc_amount, use_proxy)
            await self.approving_token(account, address, self.STAKING_ROUTER_ADDRESS, self.USDT_CONTRACT_ADDRESS, self.usdt_amount, use_proxy)
            await self.approving_token(account, address, self.STAKING_ROUTER_ADDRESS, self.MUSD_CONTRACT_ADDRESS, self.musd_amount, use_proxy)
            transactions = await self.generate_change_transactions(address, change_tx, use_proxy)
            if not transactions:
                raise ValueError("Generate Transaction Calldata Failed")
            calldata = transactions["data"]["688688"]["data"]
            estimated_gas = web3.eth.estimate_gas({
                "from": web3.to_checksum_address(address),
                "to": web3.to_checksum_address(self.STAKING_ROUTER_ADDRESS),
                "data": calldata,
            })
            max_priority_fee = web3.to_wei(1, "gwei")
            max_fee = max_priority_fee
            current_nonce = web3.eth.get_transaction_count(address, "pending")
            tx = {
                "from": web3.to_checksum_address(address),
                "to": web3.to_checksum_address(self.STAKING_ROUTER_ADDRESS),
                "data": calldata,
                "gas": int(estimated_gas * 1.2),
                "maxFeePerGas": int(max_fee),
                "maxPriorityFeePerGas": int(max_priority_fee),
                "nonce": current_nonce,
                "chainId": web3.eth.chain_id,
            }
            tx_hash = await self.send_raw_transaction_with_retries(account, web3, tx)
            receipt = await self.wait_for_receipt_with_retries(web3, tx_hash)
            self.used_nonce[address] = current_nonce + 1
            return tx_hash, receipt.blockNumber
        except (InvalidAddress, ContractLogicError) as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Invalid Contract or Address: {e}{Style.RESET_ALL}")
            return None, None
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Staking Failed: {e}{Style.RESET_ALL}")
            return None, None

    async def print_timer(self):
        """Display a countdown timer for delays between transactions."""
        delay = random.randint(self.min_delay, self.max_delay)
        for remaining in range(delay, 0, -1):
            print(
                f"{Fore.CYAN + Style.BRIGHT}[ {datetime.now().astimezone(wib).strftime('%x %X %Z')} ]{Style.RESET_ALL}"
                f"{Fore.WHITE + Style.BRIGHT} | {Style.RESET_ALL}"
                f"{Fore.BLUE + Style.BRIGHT}Wait For{Style.RESET_ALL}"
                f"{Fore.WHITE + Style.BRIGHT} {remaining} {Style.RESET_ALL}"
                f"{Fore.BLUE + Style.BRIGHT}Seconds For Next Tx...{Style.RESET_ALL}",
                end="\r",
                flush=True
            )
            await asyncio.sleep(1)

    def print_question(self):
        """Prompt user for configuration inputs."""
        while True:
            try:
                staking_count = int(input(f"{Fore.YELLOW + Style.BRIGHT}Enter Staking Count For Each Wallets -> {Style.RESET_ALL}").strip())
                if staking_count > 0:
                    self.staking_count = staking_count
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Please enter a positive number.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a number.{Style.RESET_ALL}")

        while True:
            try:
                usdc_amount = float(input(f"{Fore.YELLOW + Style.BRIGHT}Enter USDC Amount -> {Style.RESET_ALL}").strip())
                if usdc_amount > 0:
                    self.usdc_amount = usdc_amount
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Amount must be greater than 0.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a float or decimal number.{Style.RESET_ALL}")

        while True:
            try:
                usdt_amount = float(input(f"{Fore.YELLOW + Style.BRIGHT}Enter USDT Amount -> {Style.RESET_ALL}").strip())
                if usdt_amount > 0:
                    self.usdt_amount = usdt_amount
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Amount must be greater than 0.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a float or decimal number.{Style.RESET_ALL}")

        while True:
            try:
                musd_amount = float(input(f"{Fore.YELLOW + Style.BRIGHT}Enter MockUSD Amount -> {Style.RESET_ALL}").strip())
                if musd_amount > 0:
                    self.musd_amount = musd_amount
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Amount must be greater than 0.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a float or decimal number.{Style.RESET_ALL}")

        while True:
            try:
                min_delay = int(input(f"{Fore.YELLOW + Style.BRIGHT}Min Delay Each Tx -> {Style.RESET_ALL}").strip())
                if min_delay >= 0:
                    self.min_delay = min_delay
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Min Delay must be >= 0.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a number.{Style.RESET_ALL}")

        while True:
            try:
                max_delay = int(input(f"{Fore.YELLOW + Style.BRIGHT}Max Delay Each Tx -> {Style.RESET_ALL}").strip())
                if max_delay >= self.min_delay:
                    self.max_delay = max_delay
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Max Delay must be >= Min Delay.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a number.{Style.RESET_ALL}")

        while True:
            try:
                print(f"{Fore.WHITE + Style.BRIGHT}1. Run With Free Proxyscrape Proxy{Style.RESET_ALL}")
                print(f"{Fore.WHITE + Style.BRIGHT}2. Run With Private Proxy{Style.RESET_ALL}")
                print(f"{Fore.WHITE + Style.BRIGHT}3. Run Without Proxy{Style.RESET_ALL}")
                choose = int(input(f"{Fore.BLUE + Style.BRIGHT}Choose [1/2/3] -> {Style.RESET_ALL}").strip())
                if choose in [1, 2, 3]:
                    proxy_type = (
                        "With Free Proxyscrape" if choose == 1 else
                        "With Private" if choose == 2 else
                        "Without"
                    )
                    self.log(f"{Fore.GREEN + Style.BRIGHT}Run {proxy_type} Proxy Selected.{Style.RESET_ALL}")
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Please enter either 1, 2, or 3.{Style.RESET_ALL}")
            except ValueError:
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter a number (1, 2, or 3).{Style.RESET_ALL}")

        rotate = False
        if choose in [1, 2]:
            while True:
                rotate = input(f"{Fore.BLUE + Style.BRIGHT}Rotate Invalid Proxy? [y/n] -> {Style.RESET_ALL}").strip().lower()
                if rotate in ["y", "n"]:
                    rotate = rotate == "y"
                    break
                self.log(f"{Fore.RED + Style.BRIGHT}Invalid input. Enter 'y' or 'n'.{Style.RESET_ALL}")

        return choose, rotate

    async def check_connection(self, proxy_url=None):
        """Check internet connection using a proxy."""
        connector, proxy, proxy_auth = self.build_proxy_config(proxy_url)
        try:
            async with ClientSession(connector=connector, timeout=ClientTimeout(total=10)) as session:
                async with session.get(url="https://api.ipify.org?format=json", proxy=proxy, proxy_auth=proxy_auth) as response:
                    response.raise_for_status()
                    return True
        except ClientResponseError as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Connection Failed: HTTP {e.status} - {e.message}{Style.RESET_ALL}")
            return False
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Connection Failed: {e}{Style.RESET_ALL}")
            return False

    async def financial_portfolio_recommendation(self, address: str, use_proxy: bool, retries=5):
        """Fetch financial portfolio recommendation from API."""
        url = f"{self.BASE_API}/investment/financial-portfolio-recommendation"
        data = json.dumps(self.generate_recommendation_payload(address))
        headers = {
            **self.HEADERS,
            "Authorization": self.auth_tokens[address],
            "Content-Length": str(len(data)),
            "Content-Type": "application/json"
        }
        for attempt in range(retries):
            proxy_url = self.get_next_proxy_for_account(address) if use_proxy else None
            connector, proxy, proxy_auth = self.build_proxy_config(proxy_url)
            try:
                async with ClientSession(connector=connector, timeout=ClientTimeout(total=60)) as session:
                    async with session.post(url=url, headers=headers, data=data, proxy=proxy, proxy_auth=proxy_auth) as response:
                        if response.status == 201:
                            self.log(f"{Fore.GREEN + Style.BRIGHT}Portfolio Recommendation Successful (HTTP 201){Style.RESET_ALL}")
                            return await response.json()
                        else:
                            error_text = await response.text()
                            self.log(f"{Fore.RED + Style.BRIGHT}API Error {response.status}: {error_text}{Style.RESET_ALL}")
                            response.raise_for_status()
            except ClientResponseError as e:
                self.log(f"{Fore.YELLOW}Portfolio Recommendation Attempt {attempt + 1} Failed: HTTP {e.status} - {e.message}{Style.RESET_ALL}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
            except Exception as e:
                self.log(f"{Fore.YELLOW}Portfolio Recommendation Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
            if attempt == retries - 1:
                self.log(f"{Fore.RED + Style.BRIGHT}All {retries} Portfolio Recommendation Attempts Failed{Style.RESET_ALL}")
                return None
        return None

    async def generate_change_transactions(self, address: str, change_tx: list, use_proxy: bool, retries=5):
        """Generate transaction calldata from API."""
        url = f"{self.BASE_API}/investment/generate-change-transactions"
        data = json.dumps(self.generate_transactions_payload(address, change_tx))
        headers = {
            **self.HEADERS,
            "Authorization": self.auth_tokens[address],
            "Content-Length": str(len(data)),
            "Content-Type": "application/json"
        }
        for attempt in range(retries):
            proxy_url = self.get_next_proxy_for_account(address) if use_proxy else None
            connector, proxy, proxy_auth = self.build_proxy_config(proxy_url)
            try:
                async with ClientSession(connector=connector, timeout=ClientTimeout(total=60)) as session:
                    async with session.post(url=url, headers=headers, data=data, proxy=proxy, proxy_auth=proxy_auth) as response:
                        if response.status == 201:
                            self.log(f"{Fore.GREEN + Style.BRIGHT}Transaction Generation Successful (HTTP 201){Style.RESET_ALL}")
                            return await response.json()
                        else:
                            error_text = await response.text()
                            self.log(f"{Fore.RED + Style.BRIGHT}API Error {response.status}: {error_text}{Style.RESET_ALL}")
                            response.raise_for_status()
            except ClientResponseError as e:
                self.log(f"{Fore.YELLOW}Transaction Generation Attempt {attempt + 1} Failed: HTTP {e.status} - {e.message}{Style.RESET_ALL}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
            except Exception as e:
                self.log(f"{Fore.YELLOW}Transaction Generation Attempt {attempt + 1} Failed: {e}{Style.RESET_ALL}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
            if attempt == retries - 1:
                self.log(f"{Fore.RED + Style.BRIGHT}All {retries} Transaction Generation Attempts Failed{Style.RESET_ALL}")
                return None
        return None

    async def process_check_connection(self, address: str, use_proxy: bool, rotate_proxy: bool):
        """Check connection and rotate proxies if needed."""
        max_attempts = len(self.proxies) if use_proxy and rotate_proxy else 1
        attempt = 0
        while attempt < max_attempts:
            proxy = self.get_next_proxy_for_account(address) if use_proxy else None
            self.log(f"{Fore.CYAN + Style.BRIGHT}Proxy   :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {proxy or 'None'} {Style.RESET_ALL}")
            if await self.check_connection(proxy):
                return True
            if rotate_proxy and use_proxy:
                proxy = self.rotate_proxy_for_account(address)
                attempt += 1
            else:
                break
        return False

    async def process_perform_claim_faucet(self, account: str, address: str, use_proxy: bool):
        """Process faucet claim for an account."""
        next_faucet_claim_time = await self.get_next_faucet_claim_time(address, use_proxy)
        if next_faucet_claim_time is not None:
            if int(time.time()) >= next_faucet_claim_time:
                tx_hash, block_number = await self.perform_claim_faucet(account, address, use_proxy)
                if tx_hash and block_number:
                    explorer = f"https://testnet.pharosscan.xyz/tx/{tx_hash}"
                    self.log(f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}{Fore.GREEN + Style.BRIGHT} Success {Style.RESET_ALL}")
                    self.log(f"{Fore.CYAN + Style.BRIGHT}    Block   :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {block_number} {Style.RESET_ALL}")
                    self.log(f"{Fore.CYAN + Style.BRIGHT}    Tx Hash :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {tx_hash} {Style.RESET_ALL}")
                    self.log(f"{Fore.CYAN + Style.BRIGHT}    Explorer:{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {explorer} {Style.RESET_ALL}")
                else:
                    self.log(f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}{Fore.RED + Style.BRIGHT} Perform On-Chain Failed {Style.RESET_ALL}")
            else:
                formatted_next_claim = datetime.fromtimestamp(next_faucet_claim_time).astimezone(wib).strftime("%x %X %Z")
                self.log(
                    f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}"
                    f"{Fore.YELLOW + Style.BRIGHT} Already Claimed {Style.RESET_ALL}"
                    f"{Fore.MAGENTA + Style.BRIGHT}-{Style.RESET_ALL}"
                    f"{Fore.CYAN + Style.BRIGHT} Next Claim at {Style.RESET_ALL}"
                    f"{Fore.WHITE + Style.BRIGHT}{formatted_next_claim}{Style.RESET_ALL}"
                )

    async def process_perform_staking(self, account: str, address: str, use_proxy: bool):
        """Process staking for an account."""
        portfolio = await self.financial_portfolio_recommendation(address, use_proxy)
        if portfolio and portfolio.get("data", {}).get("changes"):
            change_tx = portfolio["data"]["changes"]
            tx_hash, block_number = await self.perform_staking(account, address, change_tx, use_proxy)
            if tx_hash and block_number:
                explorer = f"https://testnet.pharosscan.xyz/tx/{tx_hash}"
                self.log(f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}{Fore.GREEN + Style.BRIGHT} Success {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}    Block   :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {block_number} {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}    Tx Hash :{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {tx_hash} {Style.RESET_ALL}")
                self.log(f"{Fore.CYAN + Style.BRIGHT}    Explorer:{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {explorer} {Style.RESET_ALL}")
            else:
                self.log(f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}{Fore.RED + Style.BRIGHT} Perform On-Chain Failed {Style.RESET_ALL}")
        else:
            self.log(f"{Fore.CYAN + Style.BRIGHT}    Status  :{Style.RESET_ALL}{Fore.RED + Style.BRIGHT} GET Financial Portfolio Recommendation Failed {Style.RESET_ALL}")

    async def process_accounts(self, account: str, address: str, use_proxy: bool, rotate_proxy: bool):
        """Process an account for faucet claiming and staking."""
        if not await self.process_check_connection(address, use_proxy, rotate_proxy):
            self.log(f"{Fore.RED + Style.BRIGHT}Connection Check Failed for {self.mask_account(address)}{Style.RESET_ALL}")
            return

        web3 = await self.get_web3_with_check(address, use_proxy)
        if not web3:
            self.log(f"{Fore.RED + Style.BRIGHT}Web3 Not Connected for {self.mask_account(address)}{Style.RESET_ALL}")
            return

        self.used_nonce[address] = web3.eth.get_transaction_count(address, "pending")
        self.log(f"{Fore.CYAN + Style.BRIGHT}Faucet  :{Style.RESET_ALL}")
        await self.process_perform_claim_faucet(account, address, use_proxy)
        self.log(f"{Fore.CYAN + Style.BRIGHT}Staking :{Style.RESET_ALL}")

        for i in range(self.staking_count):
            self.log(
                f"{Fore.GREEN + Style.BRIGHT} ●{Style.RESET_ALL}"
                f"{Fore.BLUE + Style.BRIGHT} Stake {Style.RESET_ALL}"
                f"{Fore.WHITE + Style.BRIGHT}{i + 1}{Style.RESET_ALL}"
                f"{Fore.MAGENTA + Style.BRIGHT} Of {Style.RESET_ALL}"
                f"{Fore.WHITE + Style.BRIGHT}{self.staking_count}{Style.RESET_ALL}"
            )
            self.log(f"{Fore.CYAN + Style.BRIGHT}    Balance :{Style.RESET_ALL}")

            usdc_balance = await self.get_token_balance(address, self.USDC_CONTRACT_ADDRESS, use_proxy)
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       1.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {usdc_balance or 0} USDC {Style.RESET_ALL}")
            usdt_balance = await self.get_token_balance(address, self.USDT_CONTRACT_ADDRESS, use_proxy)
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       2.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {usdt_balance or 0} USDT {Style.RESET_ALL}")
            musd_balance = await self.get_token_balance(address, self.MUSD_CONTRACT_ADDRESS, use_proxy)
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       3.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {musd_balance or 0} MockUSD {Style.RESET_ALL}")

            self.log(f"{Fore.CYAN + Style.BRIGHT}    Amount  :{Style.RESET_ALL}")
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       1.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {self.usdc_amount} USDC {Style.RESET_ALL}")
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       2.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {self.usdt_amount} USDT {Style.RESET_ALL}")
            self.log(f"{Fore.MAGENTA + Style.BRIGHT}       3.{Style.RESET_ALL}{Fore.WHITE + Style.BRIGHT} {self.musd_amount} MockUSD {Style.RESET_ALL}")

            if not usdc_balance or usdc_balance < self.usdc_amount:
                self.log(f"{Fore.CYAN + Style.BRIGHT}     Status  :{Style.RESET_ALL}{Fore.YELLOW + Style.BRIGHT} Insufficient USDC Token Balance {Style.RESET_ALL}")
                break
            if not usdt_balance or usdt_balance < self.usdt_amount:
                self.log(f"{Fore.CYAN + Style.BRIGHT}     Status  :{Style.RESET_ALL}{Fore.YELLOW + Style.BRIGHT} Insufficient USDT Token Balance {Style.RESET_ALL}")
                break
            if not musd_balance or musd_balance < self.musd_amount:
                self.log(f"{Fore.CYAN + Style.BRIGHT}     Status  :{Style.RESET_ALL}{Fore.YELLOW + Style.BRIGHT} Insufficient MockUSD Token Balance {Style.RESET_ALL}")
                break

            await self.process_perform_staking(account, address, use_proxy)
            if i < self.staking_count - 1:
                await self.print_timer()

    async def main(self):
        """Main entry point for the AutoStaking bot."""
        try:
            with open("accounts.txt", "r") as file:
                accounts = [line.strip() for line in file if line.strip()]
            if not accounts:
                self.log(f"{Fore.RED + Style.BRIGHT}No accounts found in 'accounts.txt'{Style.RESET_ALL}")
                return

            use_proxy_choice, rotate_proxy = self.print_question()
            use_proxy = use_proxy_choice in [1, 2]

            while True:
                self.clear_terminal()
                self.welcome()
                self.log(
                    f"{Fore.GREEN + Style.BRIGHT}Account's Total: {Style.RESET_ALL}"
                    f"{Fore.WHITE + Style.BRIGHT}{len(accounts)}{Style.RESET_ALL}"
                )

                if use_proxy:
                    await self.load_proxies(use_proxy_choice)
                    if not self.proxies and use_proxy_choice != 3:
                        self.log(f"{Fore.RED + Style.BRIGHT}No proxies available. Exiting.{Style.RESET_ALL}")
                        return

                separator = "=" * 25
                for account in accounts:
                    address = self.generate_address(account)
                    self.log(
                        f"{Fore.CYAN + Style.BRIGHT}{separator}[{Style.RESET_ALL}"
                        f"{Fore.WHITE + Style.BRIGHT} {self.mask_account(address) or 'Invalid Address'} {Style.RESET_ALL}"
                        f"{Fore.CYAN + Style.BRIGHT}]{separator}{Style.RESET_ALL}"
                    )
                    if not address:
                        self.log(f"{Fore.RED + Style.BRIGHT}Skipping Invalid Private Key{Style.RESET_ALL}")
                        continue

                    self.auth_tokens[address] = self.generate_auth_token(address)
                    if not self.auth_tokens[address]:
                        self.log(f"{Fore.RED + Style.BRIGHT}Skipping Due to Auth Token Generation Failure{Style.RESET_ALL}")
                        continue

                    await self.process_accounts(account, address, use_proxy, rotate_proxy)
                    await asyncio.sleep(3)

                self.log(f"{Fore.CYAN + Style.BRIGHT}={Style.RESET_ALL}" * 72)
                seconds = 24 * 60 * 60
                while seconds > 0:
                    formatted_time = self.format_seconds(seconds)
                    print(
                        f"{Fore.CYAN + Style.BRIGHT}[ Wait for{Style.RESET_ALL}"
                        f"{Fore.WHITE + Style.BRIGHT} {formatted_time} {Style.RESET_ALL}"
                        f"{Fore.CYAN + Style.BRIGHT}... ]{Style.RESET_ALL}"
                        f"{Fore.WHITE + Style.BRIGHT} | {Style.RESET_ALL}"
                        f"{Fore.BLUE + Style.BRIGHT}All Accounts Have Been Processed.{Style.RESET_ALL}",
                        end="\r"
                    )
                    await asyncio.sleep(1)
                    seconds -= 1

        except FileNotFoundError:
            self.log(f"{Fore.RED + Style.BRIGHT}File 'accounts.txt' Not Found.{Style.RESET_ALL}")
        except KeyboardInterrupt:
            self.log(f"{Fore.RED + Style.BRIGHT}[ EXIT ] AutoStaking - BOT{Style.RESET_ALL}")
        except Exception as e:
            self.log(f"{Fore.RED + Style.BRIGHT}Unexpected Error: {e}{Style.RESET_ALL}")
            raise

if __name__ == "__main__":
    bot = AutoStaking()
    asyncio.run(bot.main())
