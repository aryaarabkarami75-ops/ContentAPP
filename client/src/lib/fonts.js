// Load a Google Font on demand so canvas text uses the brand typeface.
const loaded = new Set();
export async function loadFont(family, weight = 700) {
  if (!family) return;
  if (!loaded.has(family)) {
    loaded.add(family);
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family).replace(/%20/g, '+')}:wght@300;400;500;600;700;800;900&display=swap`;
    document.head.appendChild(link);
    await new Promise((r) => { link.onload = r; link.onerror = r; setTimeout(r, 4000); });
  }
  try { await Promise.race([document.fonts.load(`${weight} 40px "${family}"`, 'Aa'), new Promise((r) => setTimeout(r, 4000))]); } catch { /* fall back to system font */ }
}
export const FONT_CHOICES = ['Inter', 'Montserrat', 'Poppins', 'Roboto', 'Open Sans', 'Lato', 'Oswald', 'Bebas Neue', 'Playfair Display', 'DM Sans', 'Raleway', 'Nunito', 'Archivo Black', 'Anton', 'Lora', 'Vazirmatn'];
