"""
Génère du trafic NORMAL sur l'API de paiement.
À lancer en continu pendant toute la collecte : c'est la base "normale"
que le modèle ML apprend à reconnaître.

Usage:
    python normal_traffic.py --url http://localhost:8000 --rps 15
"""
import argparse
import random
import time
import threading
import requests

def one_user(url, stop):
    accounts = [1, 2, 3, 4]
    while not stop.is_set():
        try:
            action = random.random()
            if action < 0.5:
                # transaction normale
                a, b = random.sample(accounts, 2)
                requests.post(f"{url}/transaction",
                              json={"from_acc": a, "to_acc": b,
                                    "amount": round(random.uniform(1, 50), 2)},
                              timeout=3)
            elif action < 0.8:
                # consultation de compte
                requests.get(f"{url}/accounts/{random.choice(accounts)}", timeout=3)
            else:
                # login correct
                requests.post(f"{url}/login",
                              json={"username": "alice", "password": "demo123"},
                              timeout=3)
        except requests.RequestException:
            pass
        time.sleep(random.uniform(0.3, 1.2))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--rps", type=int, default=15, help="utilisateurs simultanés ~ débit")
    args = p.parse_args()

    stop = threading.Event()
    threads = [threading.Thread(target=one_user, args=(args.url, stop), daemon=True)
               for _ in range(args.rps)]
    for t in threads:
        t.start()
    print(f"Trafic normal lancé : ~{args.rps} utilisateurs sur {args.url}. Ctrl+C pour arrêter.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        print("\nArrêt du trafic normal.")

if __name__ == "__main__":
    main()
