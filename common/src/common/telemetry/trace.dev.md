🔍 TRACE: 1a58d606...0f94218a | 959.8ms | 16 spans
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌐 PRESENTATION LAYER
  POST /customers (959.8ms) [⚠️ UNSET] → 201 | http://127.0.0.1:8081/customers
  infraestructure.repository.input_mapping (370μs) [✅ OK]

⚙️ APPLICATION LAYER
  mediator.send (954.2ms) [✅ OK] → CustomerCreateRequest
  mediator.cache_build (70μs) [✅ OK]
  pipeline.execute (954.0ms) [✅ OK] LogggerPipeLine
  pipeline.execute (953.8ms) [✅ OK] TransactionPipeLine
  handler.execute (3.4ms) [✅ OK] Service

🏛️ DOMAIN LAYER
  entity.Customer.create (86μs) [✅ OK] → 0d582b1c-f1b0-4d8a-ae47-9f18ae3081b8
  domain.event.CustomerCreated (30μs) [✅ OK] → queued

🔧 INFRASTRUCTURE LAYER
  repository.create (2.9ms) [✅ OK]
  repository.concrete.create (1.3ms) [✅ OK]
  firestore.create.customers (999μs) [✅ OK]
  eventbus.publish(CustomerCreated) (1.2ms) [✅ OK]
    ↳ ⚙️ APPLICATION LAYER (event handler)
       handler.CustomerCreatedHandler (3.2ms) [✅ OK]
         ↳ 🔧 INFRASTRUCTURE LAYER
            outbox.save (1.4ms) [✅ OK]

📊 Summary: 959.8ms total | 16 OK, 0 ERROR | 0 external calls
📦 Domain Events:
   - CustomerCreated → 1 handler (3.2ms, OK)
