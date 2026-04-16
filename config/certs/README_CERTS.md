# TLS Certificate Management

## Generating a New Client Keypair

```bash
# 1. Generate a new private key
openssl genrsa -out client.key 2048

# 2. Create a CSR (Certificate Signing Request)
openssl req -new -key client.key -out client.csr \
  -subj "/C=US/ST=State/O=SmartSpacePulse/CN=core2-device"

# 3. Sign with the broker CA
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out client.crt -days 365 -sha256

# 4. Verify the signed certificate
openssl verify -CAfile ca.crt client.crt
```

## Updating Devices and Servers

1. Copy the new `client.crt` and `client.key` to the device or server.
2. Update `.env` paths:
   ```
   MQTT_CLIENT_CERT=config/certs/client.crt
   MQTT_CLIENT_KEY=config/certs/client.key
   ```
3. Restart the affected services:
   ```bash
   # Restart ingestor / windower
   systemctl restart ssp-ingestor
   # Or on-device: power-cycle the Core2
   ```

## Revoking an Old Certificate

```bash
# Create a CRL (Certificate Revocation List)
echo "01" > crlnumber
openssl ca -revoke old_client.crt -config openssl.cnf
openssl ca -gencrl -config openssl.cnf -out ca.crl

# Distribute ca.crl to the broker and reload
```

## File Locations

| File | Purpose |
|------|---------|
| `ca.crt` | CA certificate (public — committed) |
| `ca.key` | CA private key (secret — never commit) |
| `client.crt` | Device client certificate |
| `client.key` | Device private key |
