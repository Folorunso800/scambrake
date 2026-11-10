//! ScamBrake guard contract.
//!
//! The agent holds ONE function-call access key on this account, limited to the
//! method `pay`. A function-call key cannot attach a deposit, cannot add keys and
//! cannot transfer NEAR by itself. All it can do is call `pay` here, and `pay`
//! enforces the rules below. The money is paid out by the contract from its own
//! balance, so the rules cannot be skipped by the agent.
//!
//! Rules enforced on chain:
//!  1. receiver must not be on the blocklist (blocklist entries carry evidence)
//!  2. amount <= per_tx_cap
//!  3. receiver not on the allowlist => amount <= unlisted_per_tx_cap (0 = allowlist only)
//!  4. total paid in the current UTC day <= daily_cap
//!  5. the account must keep a small reserve so it can still pay gas and storage
use near_sdk::json_types::U128;
use near_sdk::serde::{Deserialize, Serialize};
use near_sdk::store::{IterableMap, IterableSet};
use near_sdk::{env, near, require, AccountId, NearToken, PanicOnDefault, Promise};

const DAY_NS: u64 = 86_400_000_000_000;
const MIN_REPORT_DEPOSIT: u128 = 10_000_000_000_000_000_000_000; // 0.01 NEAR, anti-spam
const RESERVE: u128 = 200_000_000_000_000_000_000_000; // 0.2 NEAR kept for gas and storage
const MAX_REPORTS_PER_ACCOUNT: usize = 10;
const MAX_TEXT: usize = 300;

#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct BlockEntry {
    pub reason: String,
    pub evidence: String,
    pub added_by: AccountId,
    pub added_at_ns: u64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone)]
pub struct Report {
    pub reporter: AccountId,
    pub reason: String,
    pub evidence: String,
    pub at_ns: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(crate = "near_sdk::serde")]
pub struct Policy {
    pub owner: AccountId,
    pub per_tx_cap: U128,
    pub daily_cap: U128,
    pub unlisted_per_tx_cap: U128,
    pub day: u64,
    pub spent_today: U128,
}

#[derive(Serialize, Deserialize)]
#[serde(crate = "near_sdk::serde")]
pub struct ReceiverInfo {
    pub account: AccountId,
    pub blocked: Option<BlockEntry>,
    pub allowlisted: bool,
    pub reports: Vec<Report>,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Guard {
    owner: AccountId,
    per_tx_cap: u128,
    daily_cap: u128,
    unlisted_per_tx_cap: u128,
    day: u64,
    spent_today: u128,
    allow: IterableSet<AccountId>,
    block: IterableMap<AccountId, BlockEntry>,
    reports: IterableMap<AccountId, Vec<Report>>,
}

fn clip(s: String, what: &str) -> String {
    require!(s.len() <= MAX_TEXT, format!("{what} longer than {MAX_TEXT} bytes"));
    s
}

#[near]
impl Guard {
    #[init]
    pub fn new(owner: AccountId, per_tx_cap: U128, daily_cap: U128, unlisted_per_tx_cap: U128) -> Self {
        require!(!env::state_exists(), "already initialised");
        require!(per_tx_cap.0 <= daily_cap.0, "per_tx_cap must be <= daily_cap");
        Self {
            owner,
            per_tx_cap: per_tx_cap.0,
            daily_cap: daily_cap.0,
            unlisted_per_tx_cap: unlisted_per_tx_cap.0,
            day: env::block_timestamp() / DAY_NS,
            spent_today: 0,
            allow: IterableSet::new(b"a"),
            block: IterableMap::new(b"b"),
            reports: IterableMap::new(b"r"),
        }
    }

    // ---------------------------------------------------------------- agent

    /// Pay `amount` yoctoNEAR from this account to `receiver`, if the rules allow it.
    /// Callable by this account itself (the agent's function-call key) or by the owner.
    pub fn pay(&mut self, receiver: AccountId, amount: U128, memo: Option<String>) -> Promise {
        let caller = env::predecessor_account_id();
        require!(
            caller == env::current_account_id() || caller == self.owner,
            "only the agent key (this account) or the owner can call pay"
        );
        let amount = amount.0;
        require!(amount > 0, "REFUSED: amount must be > 0");
        if let Some(b) = self.block.get(&receiver) {
            env::panic_str(&format!("REFUSED_BLOCKLIST: {} is blocked. reason: {} evidence: {}", receiver, b.reason, b.evidence));
        }
        require!(
            amount <= self.per_tx_cap,
            format!("REFUSED_PER_TX_CAP: {} > {} yoctoNEAR", amount, self.per_tx_cap)
        );
        if !self.allow.contains(&receiver) {
            require!(
                amount <= self.unlisted_per_tx_cap,
                format!("REFUSED_NOT_ALLOWLISTED: {} is not allowlisted, cap for unlisted receivers is {} yoctoNEAR", receiver, self.unlisted_per_tx_cap)
            );
        }
        let today = env::block_timestamp() / DAY_NS;
        if today != self.day {
            self.day = today;
            self.spent_today = 0;
        }
        require!(
            self.spent_today + amount <= self.daily_cap,
            format!("REFUSED_DAILY_CAP: {} already paid today + {} > {}", self.spent_today, amount, self.daily_cap)
        );
        let needed = env::storage_byte_cost().as_yoctonear() * env::storage_usage() as u128 + RESERVE + amount;
        require!(env::account_balance().as_yoctonear() >= needed, "REFUSED_RESERVE: not enough balance left after reserve");
        self.spent_today += amount;
        env::log_str(&format!(
            "EVENT_JSON:{{\"standard\":\"scambrake\",\"event\":\"pay\",\"receiver\":\"{}\",\"amount\":\"{}\",\"spent_today\":\"{}\",\"memo\":{}}}",
            receiver, amount, self.spent_today,
            near_sdk::serde_json::to_string(&memo.unwrap_or_default()).unwrap()
        ));
        Promise::new(receiver).transfer(NearToken::from_yoctonear(amount))
    }

    // ---------------------------------------------------------------- owner

    pub fn set_limits(&mut self, per_tx_cap: U128, daily_cap: U128, unlisted_per_tx_cap: U128) {
        self.only_owner();
        require!(per_tx_cap.0 <= daily_cap.0, "per_tx_cap must be <= daily_cap");
        self.per_tx_cap = per_tx_cap.0;
        self.daily_cap = daily_cap.0;
        self.unlisted_per_tx_cap = unlisted_per_tx_cap.0;
    }

    pub fn allow(&mut self, account: AccountId) {
        self.only_owner();
        require!(self.block.get(&account).is_none(), "account is on the blocklist, unblock it first");
        self.allow.insert(account);
    }

    pub fn disallow(&mut self, account: AccountId) {
        self.only_owner();
        self.allow.remove(&account);
    }

    /// Put an account on the shared blocklist. Evidence is required.
    pub fn block(&mut self, account: AccountId, reason: String, evidence: String) {
        self.only_owner();
        require!(!evidence.trim().is_empty(), "evidence is required");
        let entry = BlockEntry {
            reason: clip(reason, "reason"),
            evidence: clip(evidence, "evidence"),
            added_by: env::predecessor_account_id(),
            added_at_ns: env::block_timestamp(),
        };
        self.allow.remove(&account);
        self.block.insert(account, entry);
    }

    pub fn unblock(&mut self, account: AccountId) {
        self.only_owner();
        self.block.remove(&account);
    }

    // ---------------------------------------------------------------- anyone

    /// Any account (another agent, a human) can report a receiver, with evidence.
    /// A report alone does not block anyone: the owner reviews it and calls `block`.
    /// It needs a 0.01 NEAR deposit (kept, anti-spam). A function-call key cannot attach
    /// a deposit, so the paying agent itself cannot spam this.
    #[payable]
    pub fn report(&mut self, account: AccountId, reason: String, evidence: String) {
        require!(env::attached_deposit().as_yoctonear() >= MIN_REPORT_DEPOSIT, "attach at least 0.01 NEAR");
        require!(!evidence.trim().is_empty(), "evidence is required");
        let reporter = env::predecessor_account_id();
        let rep = Report {
            reporter: reporter.clone(),
            reason: clip(reason, "reason"),
            evidence: clip(evidence, "evidence"),
            at_ns: env::block_timestamp(),
        };
        let mut list = self.reports.get(&account).cloned().unwrap_or_default();
        list.retain(|r| r.reporter != reporter);
        require!(list.len() < MAX_REPORTS_PER_ACCOUNT, "too many reports for this account already");
        list.push(rep);
        self.reports.insert(account, list);
    }

    // ---------------------------------------------------------------- views

    pub fn get_policy(&self) -> Policy {
        let today = env::block_timestamp() / DAY_NS;
        Policy {
            owner: self.owner.clone(),
            per_tx_cap: self.per_tx_cap.into(),
            daily_cap: self.daily_cap.into(),
            unlisted_per_tx_cap: self.unlisted_per_tx_cap.into(),
            day: self.day,
            spent_today: (if today == self.day { self.spent_today } else { 0 }).into(),
        }
    }

    pub fn get_receiver(&self, account: AccountId) -> ReceiverInfo {
        ReceiverInfo {
            blocked: self.block.get(&account).cloned(),
            allowlisted: self.allow.contains(&account),
            reports: self.reports.get(&account).cloned().unwrap_or_default(),
            account,
        }
    }

    pub fn get_allowlist(&self) -> Vec<AccountId> {
        self.allow.iter().cloned().collect()
    }

    pub fn get_blocklist(&self) -> Vec<(AccountId, BlockEntry)> {
        self.block.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
    }

    fn only_owner(&self) {
        require!(env::predecessor_account_id() == self.owner, "owner only");
    }
}

#[cfg(test)]
mod tests {
    #![allow(unused_must_use)]
    use super::*;
    use near_sdk::test_utils::{accounts, VMContextBuilder};
    use near_sdk::testing_env;

    const N: u128 = 1_000_000_000_000_000_000_000_000;

    fn ctx(pred: AccountId, deposit: u128) -> VMContextBuilder {
        let mut b = VMContextBuilder::new();
        b.current_account_id(accounts(0))
            .predecessor_account_id(pred)
            .signer_account_id(accounts(0))
            .account_balance(NearToken::from_near(10))
            .attached_deposit(NearToken::from_yoctonear(deposit));
        b
    }

    fn setup() -> Guard {
        // accounts(0)=guard itself, accounts(1)=owner
        testing_env!(ctx(accounts(1), 0).build());
        Guard::new(accounts(1), U128(N), U128(2 * N), U128(N / 10))
    }

    #[test]
    fn allowlisted_pay_within_caps_ok() {
        let mut g = setup();
        g.allow(accounts(2));
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(2), U128(N / 2), None);
        assert_eq!(g.get_policy().spent_today.0, N / 2);
    }

    #[test]
    #[should_panic(expected = "REFUSED_BLOCKLIST")]
    fn blocked_receiver_refused() {
        let mut g = setup();
        g.block(accounts(3), "drainer".into(), "https://x.com/i/status/1".into());
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(3), U128(1), None);
    }

    #[test]
    #[should_panic(expected = "REFUSED_PER_TX_CAP")]
    fn per_tx_cap_enforced() {
        let mut g = setup();
        g.allow(accounts(2));
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(2), U128(N + 1), None);
    }

    #[test]
    #[should_panic(expected = "REFUSED_NOT_ALLOWLISTED")]
    fn unlisted_over_small_cap_refused() {
        let mut g = setup();
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(2), U128(N / 10 + 1), None);
    }

    #[test]
    fn unlisted_small_pay_ok() {
        let mut g = setup();
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(2), U128(N / 10), None);
    }

    #[test]
    #[should_panic(expected = "REFUSED_DAILY_CAP")]
    fn daily_cap_enforced() {
        let mut g = setup();
        g.allow(accounts(2));
        testing_env!(ctx(accounts(0), 0).build());
        g.pay(accounts(2), U128(N), None);
        g.pay(accounts(2), U128(N), None);
        g.pay(accounts(2), U128(1), None);
    }

    #[test]
    #[should_panic(expected = "only the agent key")]
    fn stranger_cannot_call_pay() {
        let mut g = setup();
        g.allow(accounts(2));
        testing_env!(ctx(accounts(4), 0).build());
        g.pay(accounts(2), U128(1), None);
    }

    #[test]
    #[should_panic(expected = "owner only")]
    fn agent_cannot_change_limits() {
        let mut g = setup();
        testing_env!(ctx(accounts(0), 0).build());
        g.set_limits(U128(N), U128(100 * N), U128(N));
    }

    #[test]
    fn report_needs_deposit_and_evidence() {
        let mut g = setup();
        testing_env!(ctx(accounts(4), MIN_REPORT_DEPOSIT).build());
        g.report(accounts(3), "fake airdrop".into(), "https://x.com/i/status/1".into());
        assert_eq!(g.get_receiver(accounts(3)).reports.len(), 1);
        // a report alone does not block
        assert!(g.get_receiver(accounts(3)).blocked.is_none());
    }

    #[test]
    #[should_panic(expected = "attach at least 0.01 NEAR")]
    fn report_without_deposit_refused() {
        let mut g = setup();
        testing_env!(ctx(accounts(4), 0).build());
        g.report(accounts(3), "x".into(), "y".into());
    }

    #[test]
    fn block_removes_from_allowlist() {
        let mut g = setup();
        g.allow(accounts(2));
        g.block(accounts(2), "r".into(), "e".into());
        assert!(!g.get_receiver(accounts(2)).allowlisted);
    }
}
