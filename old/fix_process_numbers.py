"""Script para corrigir números de processo incompletos no banco"""
import sqlite3

conn = sqlite3.connect('instance/intellexia.db')
cursor = conn.cursor()

# Buscar processos com números incompletos (menos de 25 caracteres)
cursor.execute("SELECT id, process_number, LENGTH(process_number) as len FROM judicial_processes WHERE LENGTH(process_number) < 25")
incomplete = cursor.fetchall()

if incomplete:
    print(f"Encontrados {len(incomplete)} processos com números incompletos:")
    for proc in incomplete:
        print(f"  ID {proc[0]}: {proc[1]} (tamanho: {proc[2]})")
    
    # Corrigir o processo específico que sabemos estar errado
    cursor.execute("UPDATE judicial_processes SET process_number = '5004423-11.2025.4.04.7100' WHERE process_number = '5004423-11.2025.4.04.710'")
    conn.commit()
    print("\n✓ Número do processo corrigido: 5004423-11.2025.4.04.710 → 5004423-11.2025.4.04.7100")
else:
    print("✓ Todos os processos têm números completos!")

# Verificar resultado
cursor.execute("SELECT process_number, LENGTH(process_number) FROM judicial_processes ORDER BY id")
print("\n--- Processos após correção ---")
for row in cursor.fetchall():
    status = "✓" if len(row[0]) == 25 else "✗"
    print(f"{status} {row[0]} - {row[1]} caracteres")

conn.close()
