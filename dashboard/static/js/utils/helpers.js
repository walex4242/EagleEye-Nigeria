/* ══════════════════════════════════════════
   helpers.js — Shared Utility Functions v3.2
   FIXED: Full location enrichment with
   client-side fallback geocoding
   ══════════════════════════════════════════ */

// ══════════════════════════════════════════
//  CLIENT-SIDE FALLBACK GEOCODER
//  Guarantees State/LGA/Town display even
//  when backend enrichment fails
// ══════════════════════════════════════════

const NigeriaGeo = (() => {
  // State bounding boxes: [min_lat, max_lat, min_lon, max_lon, capital, geo_zone]
  const STATES = {
    Abia: [4.75, 6.12, 7.0, 8.0, 'Umuahia', 'South East'],
    Adamawa: [7.48, 10.96, 11.4, 13.7, 'Yola', 'North East'],
    'Akwa Ibom': [4.32, 5.53, 7.35, 8.3, 'Uyo', 'South South'],
    Anambra: [5.68, 6.77, 6.6, 7.2, 'Awka', 'South East'],
    Bauchi: [9.3, 12.22, 8.5, 11.0, 'Bauchi', 'North East'],
    Bayelsa: [4.2, 5.35, 5.2, 6.8, 'Yenagoa', 'South South'],
    Benue: [6.4, 8.1, 6.7, 10.0, 'Makurdi', 'North Central'],
    Borno: [10.0, 13.7, 11.5, 14.7, 'Maiduguri', 'North East'],
    'Cross River': [4.28, 6.88, 7.7, 9.45, 'Calabar', 'South South'],
    Delta: [5.05, 6.5, 5.0, 6.8, 'Asaba', 'South South'],
    Ebonyi: [5.7, 6.7, 7.6, 8.3, 'Abakaliki', 'South East'],
    Edo: [5.7, 7.6, 5.0, 6.7, 'Benin City', 'South South'],
    Ekiti: [7.25, 8.1, 4.7, 5.8, 'Ado Ekiti', 'South West'],
    Enugu: [5.9, 7.1, 6.95, 7.85, 'Enugu', 'South East'],
    FCT: [8.4, 9.45, 6.7, 7.6, 'Abuja', 'North Central'],
    Gombe: [9.3, 11.2, 10.7, 12.0, 'Gombe', 'North East'],
    Imo: [5.1, 6.0, 6.6, 7.5, 'Owerri', 'South East'],
    Jigawa: [11.0, 13.0, 8.0, 10.5, 'Dutse', 'North West'],
    Kaduna: [9.0, 11.3, 6.0, 8.8, 'Kaduna', 'North West'],
    Kano: [10.3, 12.7, 7.6, 9.4, 'Kano', 'North West'],
    Katsina: [11.0, 13.4, 6.5, 8.6, 'Katsina', 'North West'],
    Kebbi: [10.5, 13.3, 3.4, 5.8, 'Birnin Kebbi', 'North West'],
    Kogi: [6.7, 8.7, 5.4, 7.8, 'Lokoja', 'North Central'],
    Kwara: [7.7, 9.8, 2.7, 6.0, 'Ilorin', 'North Central'],
    Lagos: [6.38, 6.7, 2.7, 4.35, 'Ikeja', 'South West'],
    Nasarawa: [7.7, 9.3, 7.0, 9.4, 'Lafia', 'North Central'],
    Niger: [8.3, 11.5, 3.5, 7.5, 'Minna', 'North Central'],
    Ogun: [6.3, 7.8, 2.7, 4.6, 'Abeokuta', 'South West'],
    Ondo: [5.75, 7.8, 4.3, 6.0, 'Akure', 'South West'],
    Osun: [7.0, 8.1, 4.0, 5.1, 'Osogbo', 'South West'],
    Oyo: [7.1, 9.1, 2.7, 4.6, 'Ibadan', 'South West'],
    Plateau: [8.5, 10.6, 8.2, 10.1, 'Jos', 'North Central'],
    Rivers: [4.25, 5.7, 6.5, 7.6, 'Port Harcourt', 'South South'],
    Sokoto: [11.5, 13.8, 4.0, 6.5, 'Sokoto', 'North West'],
    Taraba: [6.5, 9.6, 9.3, 11.9, 'Jalingo', 'North East'],
    Yobe: [10.5, 13.3, 9.8, 12.3, 'Damaturu', 'North East'],
    Zamfara: [11.0, 13.1, 5.4, 7.5, 'Gusau', 'North West'],
  };

  // LGA centroids: { State: [[name, lat, lon], ...] }
  const LGAS = {
    Zamfara: [
      ['Anka', 12.11, 5.93],
      ['Bakura', 12.72, 5.68],
      ['Birnin Magaji', 12.78, 6.25],
      ['Bukkuyum', 11.94, 5.6],
      ['Bungudu', 12.25, 6.52],
      ['Gummi', 12.14, 5.17],
      ['Gusau', 12.17, 6.66],
      ['Kaura Namoda', 12.59, 6.59],
      ['Maradun', 12.38, 6.33],
      ['Maru', 12.33, 6.42],
      ['Shinkafi', 13.07, 6.51],
      ['Talata Mafara', 12.57, 6.07],
      ['Tsafe', 12.14, 7.08],
      ['Zurmi', 13.15, 6.77],
    ],
    Sokoto: [
      ['Binji', 13.22, 5.24],
      ['Bodinga', 12.87, 5.17],
      ['Dange Shuni', 13.16, 5.34],
      ['Gada', 13.74, 5.79],
      ['Goronyo', 13.44, 5.68],
      ['Gudu', 13.39, 4.69],
      ['Gwadabawa', 13.36, 5.24],
      ['Illela', 13.73, 5.3],
      ['Isa', 13.22, 5.48],
      ['Kebbe', 12.37, 4.27],
      ['Kware', 13.16, 5.27],
      ['Rabah', 12.95, 5.53],
      ['Sabon Birni', 13.56, 6.14],
      ['Shagari', 12.73, 5.1],
      ['Silame', 12.87, 4.8],
      ['Sokoto North', 13.08, 5.23],
      ['Sokoto South', 13.04, 5.22],
      ['Tambuwal', 12.4, 4.65],
      ['Tangaza', 13.57, 5.42],
      ['Tureta', 12.76, 5.38],
      ['Wamako', 13.03, 5.14],
      ['Wurno', 13.29, 5.42],
      ['Yabo', 12.71, 4.93],
    ],
    Katsina: [
      ['Bakori', 11.87, 7.42],
      ['Batagarawa', 12.88, 7.6],
      ['Batsari', 12.87, 7.33],
      ['Baure', 12.76, 8.73],
      ['Bindawa', 12.63, 7.95],
      ['Charanchi', 12.63, 7.68],
      ['Dan Musa', 11.97, 7.63],
      ['Dandume', 11.55, 7.13],
      ['Danja', 11.68, 7.55],
      ['Daura', 13.03, 8.32],
      ['Dutsi', 13.03, 8.63],
      ['Dutsin Ma', 12.45, 7.5],
      ['Faskari', 11.82, 6.87],
      ['Funtua', 11.52, 7.32],
      ['Ingawa', 12.84, 8.1],
      ['Jibia', 13.34, 7.23],
      ['Kafur', 11.65, 7.67],
      ['Kaita', 13.18, 7.85],
      ['Kankara', 11.93, 7.4],
      ['Kankia', 12.34, 7.93],
      ['Katsina', 13.0, 7.6],
      ['Kurfi', 12.24, 7.82],
      ['Kusada', 12.37, 7.37],
      ["Mai'Adua", 13.19, 8.21],
      ['Malumfashi', 11.78, 7.62],
      ['Mani', 13.0, 8.54],
      ['Mashi', 12.98, 7.95],
      ['Matazu', 12.19, 7.78],
      ['Musawa', 11.95, 7.65],
      ['Rimi', 12.42, 7.63],
      ['Sabuwa', 11.57, 7.07],
      ['Safana', 12.35, 7.38],
      ['Sandamu', 13.29, 7.59],
      ['Zango', 12.95, 8.53],
    ],
    Kaduna: [
      ['Birnin Gwari', 11.22, 6.52],
      ['Chikun', 10.32, 7.33],
      ['Giwa', 11.25, 7.33],
      ['Igabi', 10.82, 7.42],
      ['Ikara', 11.17, 7.87],
      ['Jaba', 9.72, 8.03],
      ["Jema'a", 9.33, 8.25],
      ['Kachia', 9.87, 7.95],
      ['Kaduna North', 10.55, 7.43],
      ['Kaduna South', 10.48, 7.42],
      ['Kagarko', 9.58, 7.68],
      ['Kajuru', 10.32, 7.68],
      ['Kaura', 9.67, 8.42],
      ['Kauru', 10.62, 8.08],
      ['Kubau', 11.18, 7.72],
      ['Kudan', 11.17, 7.58],
      ['Lere', 10.37, 8.58],
      ['Makarfi', 11.38, 7.67],
      ['Sabon Gari', 11.17, 7.72],
      ['Sanga', 9.53, 8.52],
      ['Soba', 10.97, 8.05],
      ['Zangon Kataf', 9.78, 8.07],
      ['Zaria', 11.08, 7.72],
    ],
    Borno: [
      ['Abadam', 13.35, 13.38],
      ['Askira/Uba', 10.53, 13.0],
      ['Bama', 11.52, 13.68],
      ['Bayo', 10.58, 12.45],
      ['Biu', 10.61, 12.19],
      ['Chibok', 10.87, 12.85],
      ['Damboa', 11.15, 12.77],
      ['Dikwa', 12.03, 13.92],
      ['Gubio', 12.58, 12.72],
      ['Guzamala', 12.52, 13.15],
      ['Gwoza', 11.08, 13.7],
      ['Hawul', 10.5, 12.22],
      ['Jere', 11.88, 13.1],
      ['Kaga', 12.13, 12.38],
      ['Kala/Balge', 12.15, 14.37],
      ['Konduga', 11.65, 13.27],
      ['Kukawa', 12.92, 13.6],
      ['Kwaya Kusar', 10.45, 12.32],
      ['Mafa', 11.82, 13.53],
      ['Magumeri', 12.12, 12.82],
      ['Maiduguri', 11.85, 13.15],
      ['Marte', 12.37, 13.83],
      ['Mobbar', 12.83, 13.18],
      ['Monguno', 12.67, 13.6],
      ['Ngala', 12.33, 14.17],
      ['Nganzai', 12.45, 12.92],
      ['Shani', 10.22, 12.07],
    ],
    Niger: [
      ['Agaie', 8.95, 6.27],
      ['Agwara', 10.87, 4.62],
      ['Bida', 9.08, 6.02],
      ['Borgu', 10.23, 4.22],
      ['Bosso', 9.77, 6.48],
      ['Chanchaga', 9.62, 6.55],
      ['Edati', 9.07, 5.82],
      ['Gbako', 9.1, 6.15],
      ['Gurara', 9.32, 7.1],
      ['Katcha', 8.82, 6.42],
      ['Kontagora', 10.4, 5.47],
      ['Lapai', 9.05, 6.57],
      ['Lavun', 9.08, 5.55],
      ['Magama', 10.63, 5.12],
      ['Mariga', 10.87, 5.52],
      ['Mashegu', 10.12, 5.58],
      ['Mokwa', 9.3, 5.05],
      ['Munya', 9.55, 6.88],
      ['Paikoro', 9.43, 6.8],
      ['Rafi', 10.23, 6.37],
      ['Rijau', 10.93, 5.22],
      ['Shiroro', 9.97, 6.85],
      ['Suleja', 9.18, 7.17],
      ['Tafa', 9.15, 7.23],
      ['Wushishi', 9.73, 6.15],
    ],
    Benue: [
      ['Ado', 7.25, 7.6],
      ['Agatu', 7.58, 7.77],
      ['Apa', 7.37, 7.57],
      ['Buruku', 7.42, 9.2],
      ['Gboko', 7.32, 9.0],
      ['Guma', 7.73, 8.62],
      ['Gwer East', 7.33, 8.57],
      ['Gwer West', 7.38, 8.35],
      ['Katsina-Ala', 7.17, 9.28],
      ['Konshisha', 6.93, 9.12],
      ['Kwande', 6.87, 9.43],
      ['Logo', 7.62, 8.87],
      ['Makurdi', 7.73, 8.53],
      ['Obi', 7.12, 8.25],
      ['Ogbadibo', 7.02, 7.8],
      ['Ohimini', 7.13, 7.88],
      ['Oju', 6.85, 8.42],
      ['Okpokwu', 7.03, 7.97],
      ['Otukpo', 7.2, 8.13],
      ['Tarka', 7.55, 8.95],
      ['Ukum', 7.08, 9.42],
      ['Ushongo', 7.15, 9.05],
      ['Vandeikya', 7.08, 9.08],
    ],
    Plateau: [
      ['Barkin Ladi', 9.53, 8.9],
      ['Bassa', 9.93, 8.73],
      ['Bokkos', 9.3, 8.98],
      ['Jos East', 9.78, 9.0],
      ['Jos North', 9.93, 8.9],
      ['Jos South', 9.82, 8.85],
      ['Kanam', 9.58, 9.73],
      ['Kanke', 9.42, 9.42],
      ['Langtang North', 9.15, 9.78],
      ['Langtang South', 8.9, 9.62],
      ['Mangu', 9.52, 9.1],
      ['Mikang', 8.92, 9.72],
      ['Pankshin', 9.33, 9.43],
      ["Qua'an Pan", 9.07, 9.3],
      ['Riyom', 9.62, 8.75],
      ['Shendam', 8.88, 9.52],
      ['Wase', 9.1, 9.93],
    ],
    Adamawa: [
      ['Demsa', 9.45, 12.1],
      ['Fufore', 9.22, 12.58],
      ['Ganye', 8.43, 12.05],
      ['Girei', 9.35, 12.52],
      ['Gombi', 10.17, 12.73],
      ['Guyuk', 9.88, 12.07],
      ['Hong', 10.23, 12.93],
      ['Jada', 8.77, 12.15],
      ['Lamurde', 9.62, 11.77],
      ['Madagali', 10.87, 13.7],
      ['Maiha', 10.32, 13.17],
      ['Mayo Belwa', 9.05, 12.05],
      ['Michika', 10.62, 13.4],
      ['Mubi North', 10.27, 13.27],
      ['Mubi South', 10.18, 13.23],
      ['Numan', 9.47, 12.03],
      ['Shelleng', 9.9, 12.0],
      ['Song', 9.82, 12.63],
      ['Toungo', 8.12, 12.05],
      ['Yola North', 9.23, 12.47],
      ['Yola South', 9.18, 12.43],
    ],
    Yobe: [
      ['Bade', 12.78, 10.98],
      ['Bursari', 12.48, 11.52],
      ['Damaturu', 11.75, 11.97],
      ['Fika', 11.3, 11.32],
      ['Fune', 11.75, 11.35],
      ['Geidam', 12.9, 11.92],
      ['Gujba', 11.5, 12.25],
      ['Gulani', 11.48, 12.15],
      ['Jakusko', 12.3, 11.05],
      ['Karasuwa', 12.75, 10.75],
      ['Machina', 13.12, 10.05],
      ['Nangere', 11.88, 11.05],
      ['Nguru', 12.88, 10.45],
      ['Potiskum', 11.72, 11.07],
      ['Tarmuwa', 12.13, 11.7],
      ['Yunusari', 13.07, 11.32],
      ['Yusufari', 13.07, 11.18],
    ],
    Nasarawa: [
      ['Akwanga', 8.9, 8.38],
      ['Awe', 8.1, 8.73],
      ['Doma', 8.38, 8.35],
      ['Karu', 8.98, 7.85],
      ['Keana', 7.87, 8.75],
      ['Keffi', 8.85, 7.87],
      ['Kokona', 8.72, 8.1],
      ['Lafia', 8.5, 8.52],
      ['Nasarawa', 8.53, 7.72],
      ['Nasarawa Egon', 8.72, 8.73],
      ['Obi', 7.78, 8.68],
      ['Toto', 8.35, 7.05],
      ['Wamba', 9.05, 8.68],
    ],
    Taraba: [
      ['Ardo Kola', 8.48, 11.05],
      ['Bali', 7.85, 10.97],
      ['Donga', 7.72, 10.05],
      ['Gashaka', 7.35, 11.52],
      ['Gassol', 8.53, 10.45],
      ['Ibi', 8.18, 9.75],
      ['Jalingo', 8.9, 11.37],
      ['Karim Lamido', 9.32, 11.23],
      ['Kurmi', 6.95, 10.73],
      ['Lau', 9.18, 11.38],
      ['Sardauna', 6.75, 11.23],
      ['Takum', 7.27, 9.98],
      ['Ussa', 6.87, 10.07],
      ['Wukari', 7.87, 9.78],
      ['Yorro', 8.62, 11.27],
      ['Zing', 8.98, 11.73],
    ],
    Gombe: [
      ['Akko', 10.28, 10.95],
      ['Balanga', 9.88, 11.68],
      ['Billiri', 9.87, 11.23],
      ['Dukku', 10.82, 10.78],
      ['Funakaye', 10.58, 11.38],
      ['Gombe', 10.29, 11.17],
      ['Kaltungo', 9.82, 11.32],
      ['Kwami', 10.45, 11.12],
      ['Nafada', 10.58, 11.33],
      ['Shongom', 9.73, 11.38],
      ['Yamaltu/Deba', 10.12, 11.32],
    ],
    Bauchi: [
      ['Alkaleri', 10.27, 10.33],
      ['Bauchi', 10.31, 9.84],
      ['Bogoro', 9.73, 9.63],
      ['Dambam', 11.68, 10.83],
      ['Darazo', 10.98, 10.42],
      ['Dass', 9.97, 9.52],
      ['Gamawa', 11.88, 10.53],
      ['Ganjuwa', 10.42, 9.85],
      ['Giade', 11.38, 10.18],
      ['Itas/Gadau', 11.72, 10.1],
      ["Jama'are", 11.67, 9.93],
      ['Katagum', 12.28, 10.27],
      ['Kirfi', 10.4, 10.47],
      ['Misau', 11.32, 10.45],
      ['Ningi', 10.93, 9.55],
      ['Shira', 11.55, 10.22],
      ['Tafawa Balewa', 9.75, 9.77],
      ['Toro', 10.03, 9.1],
      ['Warji', 10.77, 9.57],
      ['Zaki', 11.82, 10.62],
    ],
    Kebbi: [
      ['Aleiro', 12.28, 4.27],
      ['Arewa Dandi', 11.82, 4.18],
      ['Argungu', 12.75, 4.52],
      ['Augie', 12.75, 4.13],
      ['Bagudo', 11.43, 4.22],
      ['Birnin Kebbi', 12.45, 4.2],
      ['Bunza', 11.93, 4.72],
      ['Dandi', 11.55, 4.35],
      ['Fakai', 11.42, 3.87],
      ['Gwandu', 12.5, 4.63],
      ['Jega', 12.22, 4.38],
      ['Kalgo', 12.32, 4.2],
      ['Koko/Besse', 11.42, 4.52],
      ['Maiyama', 12.07, 4.37],
      ['Ngaski', 11.78, 4.08],
      ['Sakaba', 10.82, 4.52],
      ['Shanga', 11.2, 3.78],
      ['Suru', 12.48, 3.95],
      ['Wasagu/Danko', 10.73, 4.42],
      ['Yauri', 10.83, 4.77],
      ['Zuru', 11.43, 5.23],
    ],
    Jigawa: [
      ['Auyo', 12.33, 9.95],
      ['Babura', 12.77, 9.02],
      ['Biriniwa', 12.75, 10.23],
      ['Birnin Kudu', 11.45, 9.48],
      ['Buji', 11.55, 9.62],
      ['Dutse', 11.77, 9.33],
      ['Gagarawa', 12.42, 9.52],
      ['Garki', 12.2, 9.8],
      ['Gumel', 12.63, 9.38],
      ['Guri', 12.78, 10.38],
      ['Gwaram', 11.28, 9.83],
      ['Gwiwa', 12.35, 9.32],
      ['Hadejia', 12.45, 10.05],
      ['Jahun', 12.17, 9.33],
      ['Kafin Hausa', 12.23, 10.32],
      ['Kaugama', 12.38, 10.38],
      ['Kazaure', 12.65, 8.42],
      ['Kiri Kasama', 12.23, 9.87],
      ['Kiyawa', 11.77, 9.62],
      ['Maigatari', 12.82, 9.45],
      ['Malam Madori', 12.58, 9.95],
      ['Miga', 12.15, 9.58],
      ['Ringim', 12.15, 9.17],
      ['Roni', 12.65, 9.72],
      ['Sule Tankarkar', 12.7, 9.18],
      ['Taura', 12.33, 9.68],
      ['Yankwashi', 12.17, 9.17],
    ],
    Kano: [
      ['Ajingi', 11.97, 9.38],
      ['Albasu', 11.62, 9.2],
      ['Bagwai', 12.15, 8.13],
      ['Bebeji', 11.63, 8.45],
      ['Bichi', 12.23, 8.23],
      ['Bunkure', 11.7, 8.55],
      ['Dala', 12.0, 8.52],
      ['Dambatta', 12.42, 8.52],
      ['Dawakin Kudu', 11.83, 8.67],
      ['Dawakin Tofa', 12.08, 8.22],
      ['Doguwa', 11.05, 8.8],
      ['Fagge', 12.0, 8.55],
      ['Gabasawa', 12.18, 8.85],
      ['Garko', 11.65, 8.78],
      ['Garun Mallam', 11.57, 8.4],
      ['Gaya', 11.87, 9.0],
      ['Gezawa', 12.07, 8.87],
      ['Gwale', 11.97, 8.5],
      ['Gwarzo', 12.17, 7.93],
      ['Kabo', 12.37, 8.15],
      ['Kano Municipal', 12.0, 8.52],
      ['Karaye', 11.78, 8.07],
      ['Kibiya', 11.48, 8.67],
      ['Kiru', 11.53, 8.12],
      ['Kumbotso', 11.87, 8.52],
      ['Kunchi', 12.37, 8.52],
      ['Kura', 11.77, 8.43],
      ['Madobi', 11.68, 8.28],
      ['Makoda', 12.33, 8.25],
      ['Minjibir', 12.2, 8.67],
      ['Nassarawa', 12.02, 8.55],
      ['Rano', 11.55, 8.58],
      ['Rimin Gado', 12.13, 8.27],
      ['Rogo', 11.55, 8.15],
      ['Shanono', 12.08, 7.97],
      ['Sumaila', 11.53, 9.03],
      ['Takai', 11.77, 9.13],
      ['Tarauni', 11.95, 8.55],
      ['Tofa', 11.93, 8.28],
      ['Tsanyawa', 12.33, 8.55],
      ['Tudun Wada', 11.42, 8.95],
      ['Ungogo', 12.07, 8.5],
      ['Warawa', 11.93, 8.72],
      ['Wudil', 11.82, 8.85],
    ],
    FCT: [
      ['Abaji', 8.47, 6.94],
      ['Abuja Municipal', 9.06, 7.49],
      ['Bwari', 9.28, 7.38],
      ['Gwagwalada', 8.94, 7.08],
      ['Kuje', 8.88, 7.23],
      ['Kwali', 8.73, 7.02],
    ],
  };

  // Major towns for nearest-town lookup
  const TOWNS = [
    ['Maiduguri', 11.85, 13.16, 'Borno'],
    ['Bama', 11.52, 13.69, 'Borno'],
    ['Gwoza', 11.08, 13.7, 'Borno'],
    ['Chibok', 10.9, 12.83, 'Borno'],
    ['Konduga', 11.65, 13.27, 'Borno'],
    ['Dikwa', 12.03, 13.92, 'Borno'],
    ['Monguno', 12.67, 13.61, 'Borno'],
    ['Damboa', 11.16, 12.76, 'Borno'],
    ['Damaturu', 11.75, 11.96, 'Yobe'],
    ['Potiskum', 11.71, 11.08, 'Yobe'],
    ['Gashua', 12.87, 11.05, 'Yobe'],
    ['Yola', 9.2, 12.5, 'Adamawa'],
    ['Mubi', 10.27, 13.26, 'Adamawa'],
    ['Michika', 10.62, 13.4, 'Adamawa'],
    ['Gombe', 10.29, 11.17, 'Gombe'],
    ['Bauchi', 10.31, 9.84, 'Bauchi'],
    ['Gusau', 12.17, 6.66, 'Zamfara'],
    ['Anka', 12.11, 5.93, 'Zamfara'],
    ['Shinkafi', 13.07, 6.5, 'Zamfara'],
    ['Tsafe', 12.17, 6.92, 'Zamfara'],
    ['Maru', 12.33, 6.4, 'Zamfara'],
    ['Dan Sadau', 12.45, 6.27, 'Zamfara'],
    ['Katsina', 13.01, 7.6, 'Katsina'],
    ['Jibia', 13.35, 7.23, 'Katsina'],
    ['Batsari', 12.88, 7.27, 'Katsina'],
    ['Funtua', 11.52, 7.32, 'Katsina'],
    ['Kaduna', 10.52, 7.44, 'Kaduna'],
    ['Zaria', 11.09, 7.71, 'Kaduna'],
    ['Kafanchan', 9.58, 8.3, 'Kaduna'],
    ['Birnin Gwari', 10.78, 6.52, 'Kaduna'],
    ['Sokoto', 13.06, 5.24, 'Sokoto'],
    ['Kano', 12.0, 8.59, 'Kano'],
    ['Makurdi', 7.73, 8.52, 'Benue'],
    ['Jos', 9.9, 8.86, 'Plateau'],
    ['Lafia', 8.5, 8.52, 'Nasarawa'],
    ['Lokoja', 7.8, 6.74, 'Kogi'],
    ['Minna', 9.61, 6.56, 'Niger'],
    ['Abuja', 9.06, 7.5, 'FCT'],
    ['Ilorin', 8.5, 4.55, 'Kwara'],
    ['Gboko', 7.32, 9.0, 'Benue'],
    ['Otukpo', 7.19, 8.13, 'Benue'],
    ['Port Harcourt', 4.82, 7.05, 'Rivers'],
    ['Warri', 5.52, 5.75, 'Delta'],
    ['Yenagoa', 4.93, 6.27, 'Bayelsa'],
    ['Benin City', 6.34, 5.6, 'Edo'],
    ['Calabar', 4.95, 8.32, 'Cross River'],
    ['Lagos', 6.52, 3.38, 'Lagos'],
    ['Ibadan', 7.39, 3.9, 'Oyo'],
    ['Abeokuta', 7.16, 3.35, 'Ogun'],
    ['Akure', 7.25, 5.19, 'Ondo'],
    ['Enugu', 6.46, 7.55, 'Enugu'],
    ['Owerri', 5.49, 7.04, 'Imo'],
    ['Awka', 6.21, 7.07, 'Anambra'],
    ['Jalingo', 8.9, 11.37, 'Taraba'],
    ['Birnin Kebbi', 12.45, 4.2, 'Kebbi'],
    ['Dutse', 11.77, 9.33, 'Jigawa'],
  ];

  function _dist(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.asin(Math.sqrt(a));
  }

  function findState(lat, lon) {
    let best = null;
    let bestDist = Infinity;

    for (const [name, bounds] of Object.entries(STATES)) {
      const [minLat, maxLat, minLon, maxLon, capital, geoZone] = bounds;
      if (lat >= minLat && lat <= maxLat && lon >= minLon && lon <= maxLon) {
        const cLat = (minLat + maxLat) / 2;
        const cLon = (minLon + maxLon) / 2;
        const d = _dist(lat, lon, cLat, cLon);
        if (d < bestDist) {
          bestDist = d;
          best = { name, capital, geoZone };
        }
      }
    }

    if (best) return best;

    // Fallback: nearest state center
    for (const [name, bounds] of Object.entries(STATES)) {
      const [minLat, maxLat, minLon, maxLon, capital, geoZone] = bounds;
      const d = _dist(lat, lon, (minLat + maxLat) / 2, (minLon + maxLon) / 2);
      if (d < bestDist) {
        bestDist = d;
        best = { name, capital, geoZone };
      }
    }

    return best || { name: 'Unknown', capital: 'Unknown', geoZone: 'Unknown' };
  }

  function findLGA(lat, lon, stateName) {
    const lgas = LGAS[stateName];
    if (!lgas || !lgas.length) return null;

    let best = null;
    let bestDist = Infinity;

    for (const [name, lLat, lLon] of lgas) {
      const d = _dist(lat, lon, lLat, lLon);
      if (d < bestDist) {
        bestDist = d;
        best = { name, distance: d };
      }
    }

    return best;
  }

  function findNearestTown(lat, lon) {
    let best = null;
    let bestDist = Infinity;

    for (const [name, tLat, tLon, state] of TOWNS) {
      const d = _dist(lat, lon, tLat, tLon);
      if (d < bestDist) {
        bestDist = d;
        best = { name, state, distance: Math.round(d * 10) / 10 };
      }
    }

    // Also check LGA centroids (often closer than major towns)
    for (const [stateName, lgas] of Object.entries(LGAS)) {
      for (const [name, lLat, lLon] of lgas) {
        const d = _dist(lat, lon, lLat, lLon);
        if (d < bestDist) {
          bestDist = d;
          best = { name, state: stateName, distance: Math.round(d * 10) / 10 };
        }
      }
    }

    return best || { name: 'Unknown', state: 'Unknown', distance: 0 };
  }

  /**
   * Full reverse geocode — returns { state, lga, nearestTown, geoZone, ... }
   * 100% client-side, runs in <1ms
   */
  function reverseGeocode(lat, lon) {
    const stateInfo = findState(lat, lon);
    const lgaInfo = findLGA(lat, lon, stateInfo.name);
    const townInfo = findNearestTown(lat, lon);

    return {
      state: stateInfo.name,
      lga: lgaInfo ? lgaInfo.name : 'Unknown LGA',
      lgaDistance: lgaInfo ? lgaInfo.distance : 0,
      nearestTown: townInfo.name,
      nearestTownDistance: townInfo.distance,
      geoZone: stateInfo.geoZone,
      stateCapital: stateInfo.capital,
    };
  }

  return { reverseGeocode, findState, findLGA, findNearestTown };
})();

window.NigeriaGeo = NigeriaGeo;

// ══════════════════════════════════════════
//  EVENT ENRICHMENT HELPER
//  Adds state/lga/town to any event object
//  that has latitude/longitude but missing
//  location fields
// ══════════════════════════════════════════

function enrichEventLocation(evt) {
  if (!evt || !evt.latitude || !evt.longitude) return evt;

  // Skip if already enriched with real data
  const hasState = evt.state && evt.state !== '—' && evt.state !== 'Unknown';
  const hasLga =
    evt.lga &&
    evt.lga !== '—' &&
    evt.lga !== 'Unknown LGA' &&
    !evt.lga.startsWith('Near ');

  if (hasState && hasLga) return evt;

  const geo = NigeriaGeo.reverseGeocode(evt.latitude, evt.longitude);

  if (!hasState) {
    evt.state = geo.state;
  }
  if (!hasLga) {
    evt.lga = geo.lga;
  }
  if (!evt.nearest_town) {
    evt.nearest_town = geo.nearestTown;
    evt.nearest_town_distance_km = geo.nearestTownDistance;
  }
  if (!evt.geo_zone) {
    evt.geo_zone = geo.geoZone;
  }

  // Also patch the nested location object if it exists
  if (evt.location) {
    if (!evt.location.state || evt.location.state === 'Unknown') {
      evt.location.state = geo.state;
    }
    if (!evt.location.lga || evt.location.lga === 'Unknown LGA') {
      evt.location.lga = geo.lga;
    }
    if (!evt.location.nearest_town) {
      evt.location.nearest_town = geo.nearestTown;
    }
    if (!evt.location.geo_zone) {
      evt.location.geo_zone = geo.geoZone;
    }
  }

  return evt;
}

window.enrichEventLocation = enrichEventLocation;

// ══════════════════════════════════════════
//  Color helpers
// ══════════════════════════════════════════

function priorityColor(p) {
  return p === 'CRITICAL'
    ? '#ff2d2d'
    : p === 'HIGH'
      ? '#ff6520'
      : p === 'ELEVATED'
        ? '#f0a500'
        : '#00d46a';
}
function confidenceColor(c) {
  return c === 'H' ? '#ff2d2d' : c === 'N' ? '#f0a500' : '#00d46a';
}
function scoreColor(s) {
  return s >= 80
    ? '#ff2d2d'
    : s >= 60
      ? '#ff6520'
      : s >= 40
        ? '#f0a500'
        : '#00d46a';
}
function vegClassColor(c) {
  return c === 'clearing'
    ? '#ff2d2d'
    : c === 'burn_scar'
      ? '#ff6520'
      : '#00d46a';
}
function vegSeverityColor(s) {
  return s === 'critical'
    ? '#ff2d2d'
    : s === 'high'
      ? '#ff6520'
      : s === 'moderate'
        ? '#f0a500'
        : '#00d46a';
}
function alertPriorityColor(p) {
  return p === 'critical'
    ? '#ff2d2d'
    : p === 'high'
      ? '#ff6520'
      : p === 'medium'
        ? '#f0a500'
        : '#00d46a';
}
function zoneColor(z) {
  if (!z) return '#6b8099';
  return z.includes('Northwest') || z.includes('Northeast')
    ? '#ff2d2d'
    : z.includes('North Central')
      ? '#f0a500'
      : '#6b8099';
}
function confidenceLabel(c) {
  return c === 'H' ? 'High' : c === 'N' ? 'Nominal' : 'Low';
}

// ══════════════════════════════════════════
//  Format helpers
// ══════════════════════════════════════════

function formatTime(t) {
  return !t || t.length < 4 ? t || '' : `${t.slice(0, 2)}:${t.slice(2)} UTC`;
}
function formatScore(s) {
  return typeof s === 'number' ? s.toFixed(0) : s || '—';
}
function relTime(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ══════════════════════════════════════════
//  Tier badge
// ══════════════════════════════════════════

function tierBadge(t) {
  if (!t) return '';
  if (t.includes('Tier 1'))
    return '<span class="badge badge-critical" style="font-size:9px;padding:1px 5px">T1</span>';
  if (t.includes('Tier 2'))
    return '<span class="badge badge-high" style="font-size:9px;padding:1px 5px">T2</span>';
  if (t.includes('Tier 3'))
    return '<span class="badge badge-elevated" style="font-size:9px;padding:1px 5px">T3</span>';
  return '<span class="badge badge-monitor" style="font-size:9px;padding:1px 5px">T4</span>';
}

// ══════════════════════════════════════════
//  Score bar HTML
// ══════════════════════════════════════════

function scoreBarHTML(value, max, color) {
  const c = color || scoreColor(value);
  const pct = Math.min(100, Math.max(0, (value / (max || 100)) * 100));
  return `
    <div class="score-bar-wrap">
      <div class="score-bar-header">
        <span>Threat Score</span>
        <span style="color:${c};font-weight:700">${value} / ${max || 100}</span>
      </div>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:${pct}%;background:${c}"></div>
      </div>
    </div>`;
}

// ══════════════════════════════════════════
//  Toast notifications
// ══════════════════════════════════════════

function showToast(msg, type = 'success', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type] || '●'}</span><span class="toast-msg">${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.transition = '0.3s ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(110%)';
    setTimeout(() => toast.remove(), 320);
  }, duration);
}

// ══════════════════════════════════════════
//  Element helpers
// ══════════════════════════════════════════

function el(id) {
  return document.getElementById(id);
}

function setText(id, val) {
  const e = el(id);
  if (e) e.textContent = val;
}

// ══════════════════════════════════════════
//  Geo helpers
// ══════════════════════════════════════════

function googleMapsUrl(lat, lon) {
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
}
function satelliteUrl(lat, lon, zoom) {
  return `https://www.google.com/maps/@${lat},${lon},${zoom || 5000}m/data=!3m1!1e3`;
}

// ══════════════════════════════════════════
//  Popup table row
// ══════════════════════════════════════════

function popupRow(label, val) {
  if (val === undefined || val === null || val === '' || val === '—') return '';
  return `<tr>
    <td style="color:#6a82a0;padding:2.5px 12px 2.5px 0;white-space:nowrap;font-size:10.5px;vertical-align:top">${label}</td>
    <td style="color:#e8eef8;font-weight:500;padding:2.5px 0;vertical-align:top">${val}</td>
  </tr>`;
}

// ══════════════════════════════════════════
//  HOTSPOT POPUP (with fallback enrichment)
// ══════════════════════════════════════════

function buildHotspotPopup(f) {
  const [lon, lat] = f.geometry.coordinates;
  const p = f.properties;

  // ── Client-side enrichment fallback ──
  enrichEventLocation(p);

  const loc = p.location || {};
  const priority = p.priority || 'MONITOR';
  const color = priorityColor(priority);
  const score = p.threat_score || 0;
  const sc = scoreColor(score);
  const cc = confidenceColor(p.confidence);

  const stateName = p.state || loc.state || '—';
  const lgaName = p.lga || loc.lga || '—';
  const nearestTown = p.nearest_town || loc.nearest_town || '';
  const townDist =
    p.nearest_town_distance_km ||
    loc.distance_km ||
    loc.nearest_town_distance_km;
  const townDir = loc.direction || loc.nearest_town_direction || '';
  const coordsDms =
    loc.coords_dms || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;
  const opDesc = loc.operational_description || '';
  const placeName = loc.nominatim_place || loc.place_name || '';
  const roadName = loc.road || '';
  const addCtx = loc.additional_context || '';
  const gmapsUrl = p.google_maps_url || googleMapsUrl(lat, lon);
  const satUrl = satelliteUrl(lat, lon, 5000);

  let townDisplay = nearestTown;
  if (nearestTown && townDist !== undefined && townDist !== null) {
    townDisplay =
      townDist < 2
        ? `<strong>${nearestTown}</strong> (within town)`
        : `<strong>${nearestTown}</strong> (${townDist}km ${townDir})`;
  }

  const dayNightStr =
    p.daynight === 'N'
      ? '🌙 Night'
      : p.daynight === 'D'
        ? '☀️ Day'
        : p.daynight || '—';

  return `
    <div style="font-family:'Segoe UI',system-ui,sans-serif;min-width:300px;max-width:360px">

      ${
        opDesc
          ? `<div style="background:${color};color:white;padding:9px 14px;padding-right:34px;font-size:12px;font-weight:700;line-height:1.4;border-radius:0">🔥 ${opDesc}</div>`
          : `<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px 6px;padding-right:34px">
             <span style="font-size:15px;font-weight:700;color:#e8eef8">🔥 Thermal Detection</span>
             <span style="font-size:10px;padding:2px 7px;border-radius:4px;font-weight:700;background:${color}22;color:${color};border:1px solid ${color}55">${priority}</span>
           </div>`
      }

      <div style="padding:${opDesc ? '10px' : '0'} 14px 14px">

        <div style="font-size:9px;color:#3a4f68;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin-bottom:5px;${opDesc ? '' : 'padding-top:2px'}">📍 Location</div>
        <table style="width:100%;border-collapse:collapse">
          ${popupRow('State', `<strong>${stateName}</strong> ${tierBadge(p.threat_tier)}`)}
          ${popupRow('LGA', `<strong>${lgaName}</strong>`)}
          ${nearestTown ? popupRow('Nearest Town', townDisplay) : ''}
          ${placeName && placeName !== nearestTown ? popupRow('Place', placeName) : ''}
          ${roadName ? popupRow('Road', roadName) : ''}
          ${popupRow('Coordinates', `<span style="font-family:monospace;font-size:10px">${coordsDms}</span>`)}
        </table>

        <div style="font-size:9px;color:#3a4f68;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin:10px 0 5px;padding-top:10px;border-top:1px solid #1a2235">🛰️ Detection Data</div>
        <table style="width:100%;border-collapse:collapse">
          ${popupRow('Confidence', `<span style="color:${cc};font-weight:700">${confidenceLabel(p.confidence)}</span>`)}
          ${popupRow('Brightness', `<strong>${p.brightness}</strong> K`)}
          ${popupRow('FRP', `<strong>${p.frp}</strong> MW`)}
          ${popupRow('Acquired', `${p.acq_date} · ${formatTime(p.acq_time)}`)}
          ${popupRow('Day/Night', dayNightStr)}
          ${popupRow('Zone', `<span style="color:${zoneColor(p.red_zone)}">${p.red_zone || '—'}</span>`)}
        </table>

        <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1a2235">
          <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
            <span style="color:#6a82a0">Threat Score</span>
            <span style="color:${sc};font-weight:700">${score} / 100</span>
          </div>
          <div style="width:100%;height:5px;background:#1a2235;border-radius:3px;overflow:hidden">
            <div style="width:${score}%;height:100%;background:${sc};border-radius:3px"></div>
          </div>
        </div>

        ${addCtx ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(59,158,255,0.06);border-radius:4px;font-size:11px;color:#3b9eff;line-height:1.4">ℹ️ ${addCtx}</div>` : ''}

        <div style="margin-top:10px;display:flex;gap:6px">
          <a href="${gmapsUrl}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#1d4ed8;color:white;padding:8px 4px;border-radius:5px;text-decoration:none;font-size:12px;font-weight:600">
            🗺️ Google Maps
          </a>
          <a href="${satUrl}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#065f46;color:white;padding:8px 4px;border-radius:5px;text-decoration:none;font-size:12px;font-weight:600">
            🛰️ Satellite
          </a>
        </div>
        <div style="margin-top:6px;text-align:center">
          <a href="/api/v1/hotspots/states?state=${encodeURIComponent(stateName)}" target="_blank"
             style="font-size:11px;color:#3b9eff;text-decoration:none">
            📊 All hotspots in ${stateName} State
          </a>
        </div>
      </div>
    </div>`;
}

// ══════════════════════════════════════════
//  VEGETATION POPUP (with fallback enrichment)
// ══════════════════════════════════════════

function buildVegPopup(evt) {
  // ── Client-side enrichment fallback ──
  enrichEventLocation(evt);

  const sev = (evt.severity || 'moderate').toLowerCase();
  const sevBadge =
    sev === 'critical'
      ? 'badge-critical'
      : sev === 'high'
        ? 'badge-high'
        : sev === 'moderate'
          ? 'badge-elevated'
          : 'badge-monitor';

  const classification = evt.classification || 'unknown';
  const classIcon =
    classification === 'clearing'
      ? '🪓'
      : classification === 'burn_scar'
        ? '🔥'
        : classification === 'regrowth'
          ? '🌱'
          : '🌿';

  const classLabel = classification.replace(/_/g, ' ');

  const confidence = evt.confidence ? Math.round(evt.confidence * 100) : 0;

  const confColor =
    confidence >= 80
      ? 'var(--critical)'
      : confidence >= 50
        ? 'var(--elevated)'
        : 'var(--monitor)';

  // ── Location fields ──
  const loc = evt.location || {};
  const state = evt.state || loc.state || '—';
  const lga = evt.lga || loc.lga || '—';
  const nearestTown = evt.nearest_town || loc.nearest_town || '';
  const townDist = evt.nearest_town_distance_km || loc.nearest_town_distance_km;
  const townDir =
    evt.nearest_town_direction || loc.nearest_town_direction || '';
  const geoZone = evt.geo_zone || loc.geo_zone || '';
  const coordsDms = evt.coords_dms || loc.coords_dms || '';
  const opDesc =
    evt.operational_description || loc.operational_description || '';
  const addCtx = evt.additional_context || loc.additional_context || '';

  let townDisplay = nearestTown;
  if (nearestTown && townDist !== undefined && townDist !== null) {
    townDisplay =
      townDist < 2
        ? `<strong>${nearestTown}</strong> (within town)`
        : `<strong>${nearestTown}</strong> (${townDist}km ${townDir})`;
  } else if (nearestTown) {
    townDisplay = `<strong>${nearestTown}</strong>`;
  }

  const gmapsUrl =
    evt.google_maps_url ||
    loc.google_maps_url ||
    `https://www.google.com/maps/search/?api=1&query=${evt.latitude},${evt.longitude}`;

  const satUrl = `https://apps.sentinel-hub.com/eo-browser/?lat=${evt.latitude}&lng=${evt.longitude}&zoom=14`;

  const nearbyHotspots = evt.nearby_hotspots || 0;
  const hotspotHtml =
    nearbyHotspots > 0
      ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(255,101,32,0.07);
                     border:1px solid rgba(255,101,32,0.2);border-radius:4px;
                     font-size:10.5px;color:#ff6520;line-height:1.4">
           🔥 ${nearbyHotspots} nearby thermal hotspot(s)
         </div>`
      : '';

  const nearbyConflicts = evt.nearby_conflicts || 0;
  const conflictHtml =
    nearbyConflicts > 0
      ? `<div style="margin-top:4px;padding:6px 8px;background:rgba(255,45,45,0.06);
                     border:1px solid rgba(255,45,45,0.15);border-radius:4px;
                     font-size:10.5px;color:#ff2d2d;line-height:1.4">
           ⚔️ ${nearbyConflicts} nearby conflict event(s)${
             evt.nearby_fatalities
               ? ` (${evt.nearby_fatalities} fatalities)`
               : ''
           }
         </div>`
      : '';

  const meanChange = evt.mean_change || 0;
  const maxChange = evt.max_change || 0;
  const changeColor =
    classification === 'regrowth' ? 'var(--monitor)' : 'var(--critical)';

  return `
    <div style="font-family:'Segoe UI',system-ui,sans-serif;min-width:300px;max-width:380px">

      <!-- Header -->
      ${
        opDesc
          ? `<div style="background:${vegSeverityColor(sev)};color:white;padding:9px 14px;
                        padding-right:34px;
                        font-size:12px;font-weight:700;line-height:1.4;border-radius:0">
               ${classIcon} ${opDesc}
             </div>`
          : `<div style="display:flex;align-items:center;justify-content:space-between;
                        padding:10px 14px 6px;padding-right:34px">
               <div style="display:flex;align-items:center;gap:8px">
                 <span style="font-size:18px">${classIcon}</span>
                 <span style="font-size:14px;font-weight:700;color:#e8eef8;
                              font-family:Rajdhani,sans-serif;letter-spacing:0.5px">
                   🌿 Vegetation Change
                 </span>
               </div>
               <span class="badge ${sevBadge}">${sev.toUpperCase()}</span>
             </div>`
      }

      <div style="padding:${opDesc ? '10' : '0'}px 14px 14px">

        <!-- LOCATION SECTION -->
        <div style="font-size:9px;color:#3a4f68;text-transform:uppercase;
                    letter-spacing:1.2px;font-weight:600;margin-bottom:5px;
                    ${opDesc ? '' : 'padding-top:2px'}">
          📍 Location
        </div>
        <table style="width:100%;border-collapse:collapse">
          ${popupRow('State', `<strong>${state}</strong>`)}
          ${popupRow('LGA', `<strong>${lga}</strong>`)}
          ${nearestTown ? popupRow('Nearest Town', townDisplay) : ''}
          ${geoZone ? popupRow('Geo Zone', geoZone) : ''}
          ${popupRow(
            'Coordinates',
            coordsDms
              ? `<span style="font-family:monospace;font-size:10px">${coordsDms}</span>`
              : `<span style="font-family:monospace;font-size:10px">${
                  evt.latitude?.toFixed(4) || '—'
                }°N, ${evt.longitude?.toFixed(4) || '—'}°E</span>`,
          )}
        </table>

        <!-- CHANGE ANALYSIS -->
        <div style="font-size:9px;color:#3a4f68;text-transform:uppercase;
                    letter-spacing:1.2px;font-weight:600;margin:10px 0 5px;
                    padding-top:10px;border-top:1px solid #1a2235">
          📊 Change Analysis
        </div>
        <table style="width:100%;border-collapse:collapse">
          ${popupRow('Type', `<span style="text-transform:capitalize">${classLabel}</span>`)}
          ${popupRow(
            'Index',
            `<span style="font-family:monospace;text-transform:uppercase">${evt.index_used || '—'}</span>`,
          )}
          ${popupRow(
            'Mean Δ',
            `<span style="font-family:monospace;color:${changeColor};font-weight:700">${
              meanChange ? meanChange.toFixed(4) : '—'
            }</span>`,
          )}
          ${popupRow(
            'Max Δ',
            `<span style="font-family:monospace;color:${changeColor}">${
              maxChange ? maxChange.toFixed(4) : '—'
            }</span>`,
          )}
          ${popupRow(
            'Area',
            `<span style="font-family:monospace">${
              evt.area_hectares?.toFixed(2) || '—'
            } ha</span> <span style="color:#6a82a0">(${evt.area_pixels || '—'} px)</span>`,
          )}
          ${popupRow('Before', evt.date_before || '—')}
          ${popupRow('After', evt.date_after || '—')}
          ${popupRow('Veg Zone', evt.vegetation_zone || '—')}
        </table>

        <!-- CONFIDENCE BAR -->
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1a2235">
          <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
            <span style="color:#6a82a0">Confidence</span>
            <span style="color:${confColor};font-weight:700;font-family:monospace">
              ${confidence}%
            </span>
          </div>
          <div style="width:100%;height:5px;background:#1a2235;border-radius:3px;overflow:hidden">
            <div style="width:${confidence}%;height:100%;background:${confColor};border-radius:3px;
                        transition:width 0.5s ease"></div>
          </div>
        </div>

        <!-- CORRELATIONS -->
        ${hotspotHtml}
        ${conflictHtml}

        ${
          addCtx
            ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(59,158,255,0.06);
                          border-radius:4px;font-size:11px;color:#3b9eff;line-height:1.4">
                 ℹ️ ${addCtx}
               </div>`
            : ''
        }

        <!-- ACTION BUTTONS -->
        <div style="margin-top:10px;display:flex;gap:6px">
          <a href="${gmapsUrl}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#1d4ed8;color:white;
                    padding:8px 4px;border-radius:5px;text-decoration:none;
                    font-size:12px;font-weight:600">
            🗺️ Google Maps
          </a>
          <a href="${satUrl}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#065f46;color:white;
                    padding:8px 4px;border-radius:5px;text-decoration:none;
                    font-size:12px;font-weight:600">
            🛰️ Satellite
          </a>
        </div>

      </div>
    </div>`;
}

// ══════════════════════════════════════════
//  MOVEMENT POPUP (with fallback enrichment)
// ══════════════════════════════════════════

function buildMovementPopup(mv) {
  // ── Enrich origin and destination with client-side geocoding ──
  if (mv.origin_lat && mv.origin_lon) {
    const originGeo = NigeriaGeo.reverseGeocode(mv.origin_lat, mv.origin_lon);
    if (!mv.origin_state || mv.origin_state === 'Unknown') {
      mv.origin_state = originGeo.state;
    }
    if (!mv.origin_nearest_town) {
      mv.origin_nearest_town = originGeo.nearestTown;
    }
    if (!mv.origin_lga) {
      mv.origin_lga = originGeo.lga;
    }
  }
  if (mv.destination_lat && mv.destination_lon) {
    const destGeo = NigeriaGeo.reverseGeocode(
      mv.destination_lat,
      mv.destination_lon,
    );
    if (!mv.destination_state || mv.destination_state === 'Unknown') {
      mv.destination_state = destGeo.state;
    }
    if (!mv.destination_nearest_town) {
      mv.destination_nearest_town = destGeo.nearestTown;
    }
    if (!mv.destination_lga) {
      mv.destination_lga = destGeo.lga;
    }
  }

  const color =
    mv.classification === 'rapid_relocation'
      ? '#ff2d2d'
      : mv.classification === 'corridor'
        ? '#f0a500'
        : '#ff6520';
  const confPct = mv.confidence ? (mv.confidence * 100).toFixed(0) : '—';

  const originLabel = mv.origin_nearest_town
    ? `${mv.origin_nearest_town}, ${mv.origin_lga || ''}, ${mv.origin_state || '—'}`
    : `${mv.origin_state || '—'} (${mv.origin_lat.toFixed(3)}°, ${mv.origin_lon.toFixed(3)}°)`;
  const destLabel = mv.destination_nearest_town
    ? `${mv.destination_nearest_town}, ${mv.destination_lga || ''}, ${mv.destination_state || '—'}`
    : `${mv.destination_state || '—'} (${mv.destination_lat.toFixed(3)}°, ${mv.destination_lon.toFixed(3)}°)`;

  const ogmaps = googleMapsUrl(mv.origin_lat, mv.origin_lon);
  const dgmaps = googleMapsUrl(mv.destination_lat, mv.destination_lon);

  return `
    <div style="font-family:'Segoe UI',system-ui,sans-serif;min-width:280px;max-width:340px">
      <div style="background:${color};color:white;padding:9px 14px;padding-right:34px;font-size:12px;font-weight:700;line-height:1.4">
        🧭 ${(mv.classification || 'movement').replace(/_/g, ' ').toUpperCase()}
      </div>
      <div style="padding:10px 14px 14px">

        <!-- MOVEMENT PATH -->
        <div style="font-size:9px;color:#3a4f68;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin-bottom:6px">📍 Movement Path</div>
        <div style="display:flex;align-items:center;gap:8px;padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;margin-bottom:8px">
          <div style="flex:1">
            <div style="font-size:9px;color:#6a82a0;font-family:monospace">FROM</div>
            <div style="font-size:11px;font-weight:600;color:#e8eef8">${originLabel}</div>
            <div style="font-size:9px;color:#6a82a0;font-family:monospace">${mv.origin_lat.toFixed(4)}°N, ${mv.origin_lon.toFixed(4)}°E</div>
          </div>
          <div style="font-size:18px;color:${color}">➤</div>
          <div style="flex:1">
            <div style="font-size:9px;color:#6a82a0;font-family:monospace">TO</div>
            <div style="font-size:11px;font-weight:600;color:#e8eef8">${destLabel}</div>
            <div style="font-size:9px;color:#6a82a0;font-family:monospace">${mv.destination_lat.toFixed(4)}°N, ${mv.destination_lon.toFixed(4)}°E</div>
          </div>
        </div>

        <table style="width:100%;border-collapse:collapse">
          ${popupRow('Distance', `<strong>${mv.distance_km}</strong> km`)}
          ${popupRow('Bearing', `${mv.bearing_degrees}°`)}
          ${popupRow('Speed', `<strong>${mv.speed_kmh}</strong> km/h`)}
          ${popupRow('Time Δ', `${mv.time_delta_hours} hrs`)}
          ${popupRow('Origin LGA', mv.origin_lga || '')}
          ${popupRow('Dest LGA', mv.destination_lga || '')}
          ${popupRow('Origin hotspots', mv.hotspot_count_origin)}
          ${popupRow('Dest hotspots', mv.hotspot_count_destination)}
        </table>

        ${
          confPct !== '—'
            ? `
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1a2235">
          <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
            <span style="color:#6a82a0">Confidence</span>
            <span style="color:${color};font-weight:700">${confPct}%</span>
          </div>
          <div style="width:100%;height:5px;background:#1a2235;border-radius:3px;overflow:hidden">
            <div style="width:${confPct}%;height:100%;background:${color};border-radius:3px"></div>
          </div>
        </div>`
            : ''
        }

        <div style="margin-top:10px;display:flex;gap:6px">
          <a href="${ogmaps}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#1d4ed8;color:white;padding:8px 4px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:600">
            📍 Origin Map
          </a>
          <a href="${dgmaps}" target="_blank" rel="noopener"
             style="flex:1;text-align:center;background:#991b1b;color:white;padding:8px 4px;border-radius:5px;text-decoration:none;font-size:11px;font-weight:600">
            📍 Destination
          </a>
        </div>
      </div>
    </div>`;
}

// ══════════════════════════════════════════
//  Export all to window
// ══════════════════════════════════════════

window.priorityColor = priorityColor;
window.confidenceColor = confidenceColor;
window.scoreColor = scoreColor;
window.vegClassColor = vegClassColor;
window.vegSeverityColor = vegSeverityColor;
window.alertPriorityColor = alertPriorityColor;
window.zoneColor = zoneColor;
window.confidenceLabel = confidenceLabel;
window.formatTime = formatTime;
window.formatScore = formatScore;
window.relTime = relTime;
window.tierBadge = tierBadge;
window.scoreBarHTML = scoreBarHTML;
window.showToast = showToast;
window.el = el;
window.setText = setText;
window.googleMapsUrl = googleMapsUrl;
window.satelliteUrl = satelliteUrl;
window.popupRow = popupRow;
window.buildHotspotPopup = buildHotspotPopup;
window.buildVegPopup = buildVegPopup;
window.buildMovementPopup = buildMovementPopup;
window.enrichEventLocation = enrichEventLocation;
window.NigeriaGeo = NigeriaGeo;
