
### **README.md**

# DMARC Monitor 📊

## Overview

DMARC Monitor is a **Prometheus-exporting service** that automatically fetches DMARC (Domain-based Message Authentication, Reporting & Conformance) reports from an **email inbox**, extracts key metrics, and exposes them for monitoring via Prometheus. These metrics can then be visualized using **Grafana** or another dashboard tool.

## Features 🚀

✅ **Automatically fetches DMARC reports** from email attachments (`.zip` or `.gz`).  
✅ **Parses XML reports** and extracts relevant metrics.  
✅ **Exposes DMARC data** via a **Prometheus metrics endpoint (`:8000/metrics`)**.  
✅ **Removes unnecessary namespaces (`xmlns`)** for compatibility.  
✅ **Deployable via Docker and Docker Compose** for ease of use.  
✅ **Uses environment variables for secure configuration** instead of `.env`.  
✅ **Supports Grafana for visualization** of DMARC trends over time.  

---

## **Metrics Exposed in Prometheus**

Once the service is running, you can query **Prometheus metrics** at:
```
http://localhost:8000/metrics
```

### **Available Metrics**
| Metric Name                              | Description                              | Labels (`domain`, `provider`, `report_id`, `report_date`) |
|------------------------------------------|------------------------------------------|-----------------------------------------------------------|
| `dmarc_passed_count`                     | Number of emails that **passed** DMARC   | ✅                                                        |
| `dmarc_failed_count`                     | Number of emails that **failed** DMARC   | ✅                                                        |
| `dmarc_last_processed_timestamp_seconds` | Timestamp of last processed DMARC report | ✅                                                        |

Example Output:
```
dmarc_passed_count{domain="example.com", provider="Google", report_id="123456789", report_date="2025-02-18"} 500
dmarc_failed_count{domain="example.com", provider="Google", report_id="123456789", report_date="2025-02-18"} 20
dmarc_last_processed_timestamp_seconds{domain="example.com", provider="Google", report_id="123456789", report_date="2025-02-18"} 1708334567.123
```

---

## **Installation & Usage**

### **1️⃣ Clone the Repository**
```sh
git clone https://github.com/yourusername/dmarc-monitor.git
cd dmarc-monitor
```

### **2️⃣ Set Up Docker Compose**
#### **Modify `docker-compose.yml` with Your Email Credentials**
Edit the `environment` section in `docker-compose.yml`:
```yaml
environment:
  EMAIL_USER: "your-email@example.com"
  EMAIL_PASS: "your-email-password"
  IMAP_SERVER: "imap.example.com"
```

### **3️⃣ Build & Start the Service**
```sh
docker-compose up -d --build
```
This will:
- **Build the Docker image**.
- **Start the DMARC monitoring service**.
- **Expose Prometheus metrics on port `8000`**.

### **4️⃣ Verify It’s Running**
Check logs to see if it's processing DMARC reports:
```sh
docker-compose logs -f
```

### **5️⃣ Query Prometheus Metrics**
Go to:
```
http://localhost:8000/metrics
```

### **6️⃣ Stop & Remove the Container**
To stop the service, run:
```sh
docker-compose down
```

---

## **Grafana Integration 📊**

To visualize DMARC reports, **add Prometheus as a data source** in Grafana, and create a dashboard using the **exported metrics**.

Example **Prometheus Query for Passed Emails**:
```promql
sum(dmarc_passed_count) by (domain)
```

Example **Prometheus Query for Failed Emails**:
```promql
sum(dmarc_failed_count) by (domain)
```

---

## **Configuration Options**

You can **modify the environment variables** to customize the setup:

| Variable     | Description                                  | Example Value              |
|-------------|----------------------------------------------|----------------------------|
| `EMAIL_USER` | Email address to fetch DMARC reports from | `your-email@example.com`   |
| `EMAIL_PASS` | Email password (or App Password)          | `your-email-password`      |
| `IMAP_SERVER` | IMAP server for your email provider       | `imap.gmail.com`           |

💡 **Tip:** If using Gmail, generate an **App Password** instead of using your real password.

---

## **Troubleshooting 🛠️**

### **Container Not Running?**
Check logs:
```sh
docker-compose logs -f
```

### **Metrics Not Updating?**
- Ensure **emails are being received** at your inbox.
- Check that **emails contain DMARC reports** in `.zip` or `.gz` format.
- Run the script manually to debug:
  ```sh
  docker-compose up
  ```

### **Invalid Credentials?**
- Make sure the **email/password** are correct.
- **Use an App Password** instead of your real password (for Gmail, Outlook, etc.).

---

## **Contributing 🤝**

Feel free to open an **issue** or submit a **pull request** if you have improvements!

---

## **License 📜**

This project is open-source and licensed under the **MIT License**.
