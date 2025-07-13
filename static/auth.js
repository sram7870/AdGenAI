document.addEventListener("DOMContentLoaded", () => {
    const emailInput = document.getElementById("email");
    const extraFields = document.getElementById("extraFields");

    emailInput.addEventListener("blur", async () => {
        const email = emailInput.value;
        if (!email.includes("@")) return;

        try {
            const response = await fetch("/auth/check_user", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email }),
            });

            const data = await response.json();
            console.log("Server response:", data);  // ✅ debugging line

            if (data.exists) {
                extraFields.classList.add("hidden");
            } else {
                extraFields.classList.remove("hidden");
            }
        } catch (err) {
            console.error("Fetch error:", err);
        }
    });
});
