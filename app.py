from flask import Flask, request, jsonify, send_from_directory
import json
import os

app = Flask(__name__)
DATA_FILE = "data.json"

# Load data from JSON file
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}  # Reset to empty if the file is corrupted
    return {}

# Save data to JSON file
def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

# Serve static HTML
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# Get all households
@app.route("/households", methods=["GET"])
def get_households():
    data = load_data()
    return jsonify(data)

# Add a household
@app.route("/households", methods=["POST"])
def add_household():
    data = load_data()
    household_name = request.json.get("household_name")
    friends = request.json.get("friends")

    if not household_name or not friends:
        return jsonify({"error": "Household name and friends are required"}), 400

    if household_name in data:
        return jsonify({"error": "Household already exists"}), 409

    # Add household
    data[household_name] = {
        "friends": {friend.strip(): 0 for friend in friends},
        "expenses": []
    }
    save_data(data)
    return jsonify({"message": f"Household '{household_name}' added successfully"}), 201



@app.route("/expenses", methods=["POST"])
def add_expense():
    data = load_data()

    try:
        # Parse incoming JSON
        household_name = request.json.get("household_name")
        payer = request.json.get("payer")
        description = request.json.get("description")
        amount = request.json.get("amount")
        participants = request.json.get("participants")

        # Validate household
        if not household_name or household_name not in data:
            return jsonify({"error": "Household not found"}), 404

        household = data[household_name]

        # Validate payer
        if not payer or payer not in household["friends"]:
            return jsonify({"error": f"Payer '{payer}' not found in household"}), 404

        # Validate participants
        if not participants or not all(p.strip() in household["friends"] for p in participants):
            return jsonify({"error": "Some participants are not in the household"}), 400

        # Validate amount
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid or missing amount"}), 400

        # Calculate share
        share = amount / len(participants)

        # Update balances
        for participant in participants:
            participant = participant.strip()  # Ensure no spaces
            household["friends"][participant] -= share  # Participants owe their share
        household["friends"][payer] += amount  # Payer is credited the full amount

        # Add the expense to the household's expense list
        household["expenses"].append({
            "payer": payer,
            "description": description.strip(),
            "amount": amount,
            "participants": [p.strip() for p in participants],
        })

        save_data(data)  # Save updated data to file
        return jsonify({"message": "Expense added successfully"}), 201

    except Exception as e:
        # Log and return generic error
        print(f"Error while adding expense: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
        

@app.route("/expenses/<household_name>/<int:expense_index>", methods=["DELETE"])
def delete_expense(household_name, expense_index):
    data = load_data()

    # Validate household
    if household_name not in data:
        return jsonify({"error": f"Household '{household_name}' not found"}), 404

    household = data[household_name]
    expenses = household["expenses"]

    # Validate expense index
    if expense_index < 0 or expense_index >= len(expenses):
        return jsonify({"error": "Expense not found"}), 404

    # Remove the expense and update balances
    expense = expenses.pop(expense_index)
    payer = expense["payer"]
    amount = expense["amount"]
    participants = expense["participants"]

    # Reverse the balance adjustments
    share = amount / len(participants)
    for participant in participants:
        household["friends"][participant] += share  # Refund the share
    household["friends"][payer] -= amount  # Deduct the payer's credit

    save_data(data)
    return jsonify({"message": "Expense deleted successfully", "deleted_expense": expense}), 200


def calculate_transactions(balances):
    """Calculate detailed transactions from balances."""
    creditors = []
    debtors = []

    # Separate creditors and debtors
    for person, balance in balances.items():
        if balance > 0:
            creditors.append((person, balance))  # Creditors: Positive balance
        elif balance < 0:
            debtors.append((person, -balance))  # Debtors: Negative balance

    # Match creditors and debtors
    transactions = []
    while creditors and debtors:
        creditor, credit_amount = creditors.pop(0)
        debtor, debt_amount = debtors.pop(0)

        amount = min(credit_amount, debt_amount)
        transactions.append(f"{debtor} owes {creditor} {amount:.2f}")

        # Update remaining amounts
        if credit_amount > debt_amount:
            creditors.insert(0, (creditor, credit_amount - amount))
        elif debt_amount > credit_amount:
            debtors.insert(0, (debtor, debt_amount - amount))

    return transactions

@app.route("/balances/<household_name>")
def get_balances(household_name):
    data = load_data()

    if household_name not in data:
        return jsonify({"error": f"Household '{household_name}' not found"}), 404

    household = data[household_name]
    balances = household["friends"]

    # Calculate transactions from balances
    transactions = calculate_transactions(balances)

    # Get the last 20 expenses
    expenses = household["expenses"][-20:]  # Slice the last 20 expenses

    # Prepare the balance table
    balance_table = []
    for person, balance in balances.items():
        balance_table.append({"name": person, "balance": balance})

    return jsonify({
        "balances": balances,
        "transactions": transactions,
        "balance_table": balance_table,
        "recent_expenses": expenses
    })


@app.route("/balances/<household_name>/<member_name>")
def get_member_balances(household_name, member_name):
    data = load_data()

    if household_name not in data:
        return jsonify({"error": f"Household '{household_name}' not found"}), 404

    balances = data[household_name]["friends"]
    transactions = calculate_transactions(balances)

    # Find who owes this member and whom this member owes
    owes = []
    owed_by = []

    for transaction in transactions:
        debtor, creditor, amount = parse_transaction(transaction)
        if debtor == member_name:
            owes.append({"to": creditor, "amount": amount})
        elif creditor == member_name:
            owed_by.append({"from": debtor, "amount": amount})

    return jsonify({
        "member": member_name,
        "owes": owes,
        "owed_by": owed_by
    })


def parse_transaction(transaction):
    """Helper to parse transactions like 'darsh owes sudiksha 5.00'."""
    parts = transaction.split()
    debtor = parts[0]
    creditor = parts[2]
    amount = float(parts[3])
    return debtor, creditor, amount


if __name__ == "__main__":
    app.run(debug=True)
