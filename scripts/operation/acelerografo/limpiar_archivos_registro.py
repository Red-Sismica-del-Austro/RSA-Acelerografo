
import os
import sys

# ///////////////////////////////// Principal /////////////////////////////////

if __name__ == '__main__':
    
    #******************************************************************************
    #Obtiene el nombre de todos los archivos:
    #Lista los archivos del directorio a subir
    rutaCarpeta = "/home/rsa/resultados/registro-continuo/"
    listaMeses=[] 
    #print(rutaCarpeta)
    listaArchivos = os.listdir(rutaCarpeta)
    listaArchivosOrdenada = sorted(listaArchivos) 
    #listaArchivosOrdenada = listaArchivosOrdenada[0:(len(listaArchivosOrdenada)-3)]
    #print(listaArchivosOrdenada)    
    #******************************************************************************
    
    #******************************************************************************
    #Numero de meses de datos que se desea conservar (minimo 1):
    numMeses = 3
    
    try:
        #Obtiene el prefijo del maximo mes requerido:
        for i in listaArchivosOrdenada: 
            nombreArchivo = i
            #print(nombreArchivo[7:11])
            listaMeses.append(nombreArchivo[0:10])
        
        #Crea un set con el nombre de los meses:
        #print(set(listaMeses))
        setMeses = sorted(set(listaMeses))
        #print(setMeses)
        indiceUmbral = len(setMeses)-numMeses
        #print(indiceUmbral)
        if (indiceUmbral<0):
            #print('Datos insuficientes')
            sys.exit(1)
        mesUmbral = setMeses[indiceUmbral]
        print(mesUmbral)
        #******************************************************************************
        
        #******************************************************************************
        #Borra todos los archivos excepto los correspondientes al numero de meses establecido:    
        for nombreArchivo in listaArchivosOrdenada: 
            if (nombreArchivo[0:10]<mesUmbral):
                print(nombreArchivo)
                pathArchivo = rutaCarpeta + nombreArchivo
                #print(pathArchivo)
                os.remove(pathArchivo)
    except:
        print('Datos insuficientes')
    #******************************************************************************
        
# /////////////////////////////////////////////////////////////////////////////          